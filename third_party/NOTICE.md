# Third-party notices

Parts of `most_sprite.pipeline.echelle`, the ESPaDOnS raw adapter, the OLAPA ThAr
wavelength identification bootstrap, and its frozen thorium/argon line list were
selectively rewritten from algorithmic responsibilities and data in GAMSE at commit
`4d91ead6d8380b75a5a445c2dae78429bc23e0c9` by Liang Wang and contributors.
GAMSE is licensed under Apache License 2.0. The retained license is in
`third_party/licenses/Apache-2.0.txt`; exact source and target hashes are frozen in
`third_party/gamse-source-manifest.yaml`. The manifest also pins the upstream OLAPA
lamp reference `wlcalib_2495167c.fits` by HTTPS URI, MD5, and SHA-256; only derived
bootstrap coefficients are shipped.

MOST-SPRITE does not import, package, install, or download GAMSE at runtime.
