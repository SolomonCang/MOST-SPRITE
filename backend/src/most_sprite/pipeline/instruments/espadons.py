"""CFHT ESPaDOnS/OLAPA raw-file adapter.

The readout and overscan responsibilities are a SPRITE-native rewrite of the
audited GAMSE ESPaDOnS frame handling at commit
4d91ead6d8380b75a5a445c2dae78429bc23e0c9.  No GAMSE module is imported at
runtime.  FITS section keywords are authoritative so both the 2016 layout and
newer two-amplifier OLAPA layouts pass through the same explicit transform.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits
from numpy.typing import NDArray
from scipy.ndimage import median_filter

from most_sprite.domain.enums import DataMode, DQBit
from most_sprite.errors import SpriteError
from most_sprite.pipeline.echelle.models import CalibrationFrame
from most_sprite.pipeline.instruments.base import (
    DemodulationModel,
    DetectorProfile,
    RawDescriptor,
)

_SEQUENCE_RE = re.compile(
    r"\b([QUV])\s+exposure\s+([1-4])(?:\D+sequence\s+(\d+))?",
    re.IGNORECASE,
)
_FITS_SECTION_RE = re.compile(r"^\[\s*(-?\d+)\s*:\s*(-?\d+)\s*,\s*(-?\d+)\s*:\s*(-?\d+)\s*\]$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class FitsSection:
    x1: int
    x2: int
    y1: int
    y2: int

    @property
    def x_slice(self) -> slice:
        return slice(min(self.x1, self.x2) - 1, max(self.x1, self.x2))

    @property
    def y_slice(self) -> slice:
        return slice(min(self.y1, self.y2) - 1, max(self.y1, self.y2))

    @property
    def flip_x(self) -> bool:
        return self.x2 < self.x1

    @property
    def flip_y(self) -> bool:
        return self.y2 < self.y1

    def extract(self, array: NDArray[Any]) -> NDArray[Any]:
        result = array[self.y_slice, self.x_slice]
        if self.flip_y:
            result = result[::-1]
        if self.flip_x:
            result = result[:, ::-1]
        return result


def parse_fits_section(value: str, *, shape: tuple[int, int] | None = None) -> FitsSection:
    match = _FITS_SECTION_RE.match(value.strip())
    if match is None:
        raise SpriteError(
            "FITS_SECTION_INVALID",
            f"invalid FITS section: {value}",
            status_code=422,
        )
    x1, x2, y1, y2 = (int(item) for item in match.groups())
    if min(x1, x2, y1, y2) < 1:
        raise SpriteError("FITS_SECTION_INVALID", "FITS sections are one-indexed")
    if shape is not None:
        rows, columns = shape
        if max(x1, x2) > columns or max(y1, y2) > rows:
            raise SpriteError(
                "FITS_SECTION_OUT_OF_RANGE",
                f"section {value} exceeds image shape {shape}",
                status_code=422,
            )
    return FitsSection(x1=x1, x2=x2, y1=y1, y2=y2)


def _json_header(header: fits.Header) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for card in header.cards:
        key = card.keyword.strip()
        if not key or key in {"COMMENT", "HISTORY", "", "CHECKSUM", "DATASUM"}:
            continue
        value = card.value
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
        else:
            result[key] = str(value)
    return result


def _first_value(header: fits.Header | dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = header.get(key)
        if value not in (None, ""):
            return value
    return default


class ESPaDOnSAdapter:
    name = "ESPADONS"
    version = "espadons-olapa-v1"

    def _open_header(self, path: Path) -> tuple[fits.Header, int | None, tuple[int, int] | None]:
        try:
            with fits.open(path, memmap=False, lazy_load_hdus=True) as hdul:
                image_index = next(
                    (
                        index
                        for index, hdu in enumerate(hdul)
                        if hdu.header.get("NAXIS") == 2
                        and int(hdu.header.get("NAXIS1", 0)) > 0
                        and int(hdu.header.get("NAXIS2", 0)) > 0
                    ),
                    None,
                )
                if image_index is None:
                    header = hdul[0].header.copy()
                    return header, None, None
                header = hdul[image_index].header.copy()
                shape = (int(header["NAXIS2"]), int(header["NAXIS1"]))
                return header, image_index, shape
        except (OSError, KeyError, ValueError) as exc:
            raise SpriteError(
                "FITS_READ_FAILED",
                f"cannot inspect {path.name}: {exc}",
                status_code=422,
            ) from exc

    @staticmethod
    def _detector(header: fits.Header) -> str:
        detector = str(_first_value(header, "DETECTOR", "DETNAM", default="UNKNOWN")).strip()
        normalized = detector.upper()
        if "OLAPA" in normalized or "CCD42-90" in normalized:
            return "OLAPA"
        if "EEV" in normalized:
            raise SpriteError(
                "UNSUPPORTED_DETECTOR",
                "ESPaDOnS EEV1 is outside the v1 detector authority",
                status_code=422,
                details={"detector": detector},
            )
        raise SpriteError(
            "UNSUPPORTED_DETECTOR",
            "the FITS header does not identify the supported OLAPA detector",
            status_code=422,
            details={"detector": detector},
        )

    @staticmethod
    def _role(path: Path, header: fits.Header, image_hdu: int | None) -> str:
        obstype = str(_first_value(header, "OBSTYPE", "IMAGETYP", default="")).upper()
        suffix = path.name.lower()
        if image_hdu is None or suffix.endswith(("i.fits", "p.fits")):
            return "REFERENCE_ONLY"
        if "BIAS" in obstype or suffix.endswith("b.fits.fz"):
            return "BIAS"
        if "FLAT" in obstype or suffix.endswith("f.fits.fz"):
            return "FLAT"
        if "COMPAR" in obstype or "THAR" in obstype or suffix.endswith("c.fits.fz"):
            return "THAR"
        if "ALIGN" in obstype or "FABRY" in obstype or suffix.endswith("a.fits.fz"):
            return "ALIGNMENT"
        if "OBJ" in obstype or suffix.endswith("o.fits.fz"):
            return "SCIENCE"
        return "UNKNOWN"

    def inspect(self, path: Path, *, relative_path: str) -> RawDescriptor:
        header, image_hdu, _ = self._open_header(path)
        role = self._role(path, header, image_hdu)
        detector = (
            self._detector(header)
            if role != "REFERENCE_ONLY"
            else str(_first_value(header, "DETECTOR", "DETNAM", default="OLAPA"))
        )
        sequence_match = _SEQUENCE_RE.search(str(header.get("CMMTSEQ", "")))
        stokes = sequence_match.group(1).upper() if sequence_match else None
        sub_index = int(sequence_match.group(2)) if sequence_match else None
        sequence_number = (
            int(sequence_match.group(3))
            if sequence_match is not None and sequence_match.group(3)
            else None
        )
        mode = DataMode(f"POL_{stokes}") if stokes else None
        date_obs = str(_first_value(header, "DATE-OBS", "DATE", default="UNKNOWN"))
        utc_obs = str(_first_value(header, "UTC-OBS", "UT", default=""))
        observed_at = date_obs if "T" in date_obs else f"{date_obs}T{utc_obs}".rstrip("T")
        readout_mode = "|".join(
            str(_first_value(header, key, default="UNKNOWN"))
            for key in ("CCDBIN1", "CCDBIN2", "AMPLIST", "EREADSPD")
        )
        return RawDescriptor(
            path=path,
            relative_path=relative_path,
            size=path.stat().st_size,
            sha256=sha256_file(path),
            role=role,
            instrument=self.name,
            detector=detector,
            source_format="CFHT_FITS_FPACK" if path.suffix.lower() == ".fz" else "CFHT_FITS",
            image_hdu=image_hdu,
            mode=mode,
            stokes=stokes,
            sub_index=sub_index,
            sequence_number=sequence_number,
            target_name=str(_first_value(header, "OBJECT", "OBJNAME", default="UNKNOWN")).strip(),
            exposure_time=float(_first_value(header, "EXPTIME", "EXPOSURE", default=0.0)),
            observing_night=date_obs[:10],
            observed_at=observed_at if observed_at != "UNKNOWN" else None,
            readout_mode=readout_mode,
            header=_json_header(header),
        )

    def group_science(self, descriptors: list[RawDescriptor]) -> list[dict[str, Any]]:
        science = sorted(
            (item for item in descriptors if item.role == "SCIENCE"),
            key=lambda item: (item.observed_at or "", item.relative_path),
        )
        buckets: dict[tuple[str, str, str, int], list[RawDescriptor]] = {}
        fallback_counters: dict[tuple[str, str, str], int] = {}
        for item in science:
            if item.stokes is None or item.sub_index is None or item.mode is None:
                raise SpriteError(
                    "INCOMPLETE_MODULATION_GROUP",
                    f"science frame {item.relative_path} lacks a parseable CMMTSEQ",
                    status_code=422,
                )
            prefix = (item.observing_night, item.target_name, item.stokes)
            if item.sequence_number is None:
                if item.sub_index == 1:
                    fallback_counters[prefix] = fallback_counters.get(prefix, 0) + 1
                sequence_number = fallback_counters.get(prefix, 0)
            else:
                sequence_number = item.sequence_number
            buckets.setdefault((*prefix, sequence_number), []).append(item)
        groups: list[dict[str, Any]] = []
        for key, items in sorted(buckets.items()):
            indices = [item.sub_index for item in items]
            if len(items) != 4 or set(indices) != {1, 2, 3, 4}:
                raise SpriteError(
                    "INCOMPLETE_MODULATION_GROUP",
                    "an ESPaDOnS polarization sequence must contain exposures 1, 2, 3 and 4",
                    status_code=422,
                    details={"group": key, "sub_indices": indices},
                )
            ordered = sorted(items, key=lambda item: item.sub_index or 0)
            mode = ordered[0].mode
            assert mode is not None
            groups.append(
                {
                    "group_key": ":".join(str(part) for part in key),
                    "target_name": key[1],
                    "mode": mode.value,
                    "stokes": key[2],
                    "observing_night": key[0],
                    "sequence_number": key[3],
                    "exposure_time": float(np.mean([item.exposure_time for item in ordered])),
                    "artifacts": [item.relative_path for item in ordered],
                    "sub_indices": [1, 2, 3, 4],
                }
            )
        return groups

    @staticmethod
    def _section_values(
        header: fits.Header, shape: tuple[int, int]
    ) -> tuple[FitsSection, list[tuple[str, FitsSection]]]:
        data_value = str(header.get("DATASEC", f"[1:{shape[1]},1:{shape[0]}]"))
        data_section = parse_fits_section(data_value, shape=shape)
        overscans: list[tuple[str, FitsSection]] = []
        for key in ("BSECA", "BSECB", "BIASSEC", "BIASSEC1", "BIASSEC2", "OVRSECA", "OVRSECB"):
            value = header.get(key)
            if value:
                section = parse_fits_section(str(value), shape=shape)
                if all(section != existing for _, existing in overscans):
                    overscans.append((key, section))
        if not overscans:
            left_width = min(data_section.x1, data_section.x2) - 1
            right_start = max(data_section.x1, data_section.x2)
            if left_width > 0:
                overscans.append(
                    (
                        "INFERRED_LEFT",
                        FitsSection(1, left_width, data_section.y1, data_section.y2),
                    )
                )
            if right_start < shape[1]:
                overscans.append(
                    (
                        "INFERRED_RIGHT",
                        FitsSection(
                            right_start + 1,
                            shape[1],
                            data_section.y1,
                            data_section.y2,
                        ),
                    )
                )
        if not overscans:
            raise SpriteError(
                "CALIBRATION_MISSING",
                "OLAPA raw frame has no explicit or inferable overscan section",
                status_code=422,
            )
        return data_section, overscans

    def detector_profile(self, descriptor: RawDescriptor) -> DetectorProfile:
        if descriptor.image_hdu is None:
            raise SpriteError("FITS_IMAGE_MISSING", "raw descriptor has no 2D image")
        header = descriptor.header
        rows = int(header.get("NAXIS2", 0))
        columns = int(header.get("NAXIS1", 0))
        shape = (rows, columns)
        data_value = str(header.get("DATASEC", f"[1:{columns},1:{rows}]"))
        data_section, overscans = self._section_values(fits.Header(header), shape)
        gains = tuple(
            float(value)
            for value in (
                _first_value(header, "GAINA", "GAIN", default=1.3),
                _first_value(header, "GAINB", "GAIN", default=1.3),
            )
        )
        read_noise = tuple(
            float(value)
            for value in (
                _first_value(header, "RDNOISEA", "RDNOISE", default=4.2),
                _first_value(header, "RDNOISEB", "RDNOISE", default=4.1),
            )
        )
        canonical_shape = (
            abs(data_section.x2 - data_section.x1) + 1,
            abs(data_section.y2 - data_section.y1) + 1,
        )
        return DetectorProfile(
            instrument=self.name,
            detector="OLAPA",
            version=self.version,
            gain_e_per_adu=gains,
            read_noise_e=read_noise,
            saturation_adu=float(_first_value(header, "SATURATE", default=65535.0)),
            raw_shape=shape,
            canonical_shape=canonical_shape,
            data_section=data_value,
            overscan_sections=tuple(f"{key}:{section}" for key, section in overscans),
            axis_transform="DATASEC[y,x] -> transpose -> [cross_dispersion,dispersion]",
        )

    def _read(self, path: Path) -> tuple[NDArray[np.uint16], fits.Header, int]:
        header, image_hdu, _ = self._open_header(path)
        if image_hdu is None:
            raise SpriteError("FITS_IMAGE_MISSING", f"{path.name} has no 2D raw image")
        self._detector(header)
        with fits.open(path, memmap=False) as hdul:
            data = np.asarray(hdul[image_hdu].data, dtype=np.uint16)
        return data, header, image_hdu

    def canonical_image(
        self, path: Path
    ) -> tuple[NDArray[np.uint16], dict[str, Any], DetectorProfile]:
        data, header, image_hdu = self._read(path)
        descriptor = self.inspect(path, relative_path=path.name)
        profile = self.detector_profile(descriptor)
        data_section, _ = self._section_values(header, data.shape)
        canonical = data_section.extract(data).T.copy()
        provenance = {
            "source_image_hdu": image_hdu,
            "source_shape": list(data.shape),
            "canonical_shape": list(canonical.shape),
            "data_section": str(header.get("DATASEC", "FULL")),
            "axis_transform": profile.axis_transform,
            "adapter": self.version,
        }
        return canonical, provenance, profile

    def preprocess(
        self,
        path: Path,
        *,
        master_bias: NDArray[np.float64] | None = None,
        master_bias_variance: NDArray[np.float64] | None = None,
        flat_response: NDArray[np.float64] | None = None,
        flat_variance: NDArray[np.float64] | None = None,
        flat_dq: NDArray[np.uint32] | None = None,
    ) -> tuple[CalibrationFrame, dict[str, Any], DetectorProfile]:
        raw, header, _ = self._read(path)
        descriptor = self.inspect(path, relative_path=path.name)
        profile = self.detector_profile(descriptor)
        data_section, overscans = self._section_values(header, raw.shape)
        corrected = raw.astype(np.float64)
        row_models: list[NDArray[np.float64]] = []
        for _, section in overscans:
            sample = section.extract(corrected)
            row_level = np.nanmedian(sample, axis=1)
            if row_level.size == raw.shape[0] and row_level.size != (
                abs(data_section.y2 - data_section.y1) + 1
            ):
                row_level = row_level[data_section.y_slice]
                if data_section.flip_y:
                    row_level = row_level[::-1]
            size = min(501, row_level.size - (1 - row_level.size % 2))
            if size >= 5:
                row_level = median_filter(row_level, size=size, mode="nearest")
            row_models.append(row_level)
        science = data_section.extract(corrected)
        raw_science = data_section.extract(raw)
        if len(row_models) >= 2:
            if any(model.size != science.shape[0] for model in row_models):
                raise SpriteError(
                    "FITS_SECTION_INVALID",
                    "overscan and DATASEC rows do not align",
                    status_code=422,
                )
            split = science.shape[1] // 2
            science[:, :split] -= row_models[0][:, None]
            science[:, split:] -= row_models[-1][:, None]
            gain = np.empty(science.shape, dtype=np.float64)
            noise = np.empty(science.shape, dtype=np.float64)
            gain[:, :split] = profile.gain_e_per_adu[0]
            gain[:, split:] = profile.gain_e_per_adu[-1]
            noise[:, :split] = profile.read_noise_e[0]
            noise[:, split:] = profile.read_noise_e[-1]
        else:
            if row_models[0].size != science.shape[0]:
                raise SpriteError(
                    "FITS_SECTION_INVALID",
                    "overscan and DATASEC rows do not align",
                    status_code=422,
                )
            science -= row_models[0][:, None]
            gain = np.full(science.shape, float(np.mean(profile.gain_e_per_adu)))
            noise = np.full(science.shape, float(np.mean(profile.read_noise_e)))
        science *= gain
        variance = np.clip(science, 0.0, None) + noise**2
        science = science.T.copy()
        variance = variance.T.copy()
        dq = np.zeros(science.shape, dtype=np.uint32)
        saturated = raw_science.T >= profile.saturation_adu
        dq[saturated] |= DQBit.SATURATED
        invalid = ~np.isfinite(science)
        dq[invalid] |= DQBit.BAD_PIXEL
        if master_bias is not None:
            if master_bias.shape != science.shape:
                raise SpriteError("CALIBRATION_SHAPE_MISMATCH", "master bias shape differs")
            science -= master_bias
            if master_bias_variance is not None:
                if master_bias_variance.shape != science.shape:
                    raise SpriteError(
                        "CALIBRATION_SHAPE_MISMATCH", "master bias variance shape differs"
                    )
                variance += master_bias_variance
        if flat_response is not None:
            if flat_response.shape != science.shape:
                raise SpriteError("CALIBRATION_SHAPE_MISMATCH", "flat shape differs")
            bad_flat = ~np.isfinite(flat_response) | (flat_response <= 0)
            safe_flat = np.where(bad_flat, 1.0, flat_response)
            before_flat = science.copy()
            science /= safe_flat
            variance /= safe_flat**2
            if flat_variance is not None:
                if flat_variance.shape != science.shape:
                    raise SpriteError("CALIBRATION_SHAPE_MISMATCH", "flat variance shape differs")
                valid_flat_variance = (
                    ~bad_flat
                    & np.isfinite(flat_variance)
                    & (flat_variance >= 0)
                    & np.isfinite(before_flat)
                )
                flat_term = np.zeros(science.shape, dtype=np.float64)
                flat_term[valid_flat_variance] = (
                    before_flat[valid_flat_variance] ** 2
                    * flat_variance[valid_flat_variance]
                    / safe_flat[valid_flat_variance] ** 4
                )
                variance += flat_term
                dq[~valid_flat_variance] |= DQBit.BAD_PIXEL
            if flat_dq is not None:
                if flat_dq.shape != science.shape:
                    raise SpriteError("CALIBRATION_SHAPE_MISMATCH", "flat DQ shape differs")
                dq |= flat_dq
            dq[bad_flat] |= DQBit.BAD_PIXEL
        provenance = {
            "algorithm": "espadons_olapa_preprocess_v1",
            "adapter": self.version,
            "source": str(path),
            "source_image_hdu": descriptor.image_hdu,
            "data_section": profile.data_section,
            "overscan_sections": list(profile.overscan_sections),
            "gain_e_per_adu": list(profile.gain_e_per_adu),
            "read_noise_e": list(profile.read_noise_e),
            "axis_transform": profile.axis_transform,
            "master_bias_applied": master_bias is not None,
            "master_bias_variance_applied": master_bias_variance is not None,
            "flat_response_applied": flat_response is not None,
            "flat_variance_applied": flat_variance is not None,
            "flat_dq_applied": flat_dq is not None,
        }
        return (
            CalibrationFrame(
                data=science,
                variance=variance,
                dq=dq,
                unit="electron",
                coordinates={
                    "cross_dispersion": np.arange(science.shape[0], dtype=np.float64),
                    "dispersion": np.arange(science.shape[1], dtype=np.float64),
                },
                config_version=self.version,
                provenance=provenance,
            ),
            _json_header(header),
            profile,
        )

    def demodulation_model(self, mode: DataMode) -> DemodulationModel:
        if not mode.is_polarimetric:
            raise ValueError("ESPaDOnS demodulation requires POL_Q, POL_U or POL_V")
        return DemodulationModel(
            version=f"{self.version}-ratio-log-cfht-sign-v2",
            # The O/E beam ratio produced by the OLAPA extraction has the
            # opposite orientation to the archived Libre-ESpRIT Stokes
            # convention.  BD+59 389 (HD 236928) fixes this otherwise
            # ambiguous global sign: the vector below recovers its catalogued
            # negative Q and U and ~98 degree position angle.  The separate U
            # output sign then applies the explicit CFHT archive convention.
            science_signs=(-1, 1, 1, -1),
            null1_signs=(1, 1, -1, -1),
            null2_signs=(1, -1, 1, -1),
            output_sign=-1.0 if mode is DataMode.POL_U else 1.0,
        )
