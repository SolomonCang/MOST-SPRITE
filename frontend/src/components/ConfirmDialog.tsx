import { AlertTriangle } from "lucide-react";
import { useEffect, useRef } from "react";
import { useI18n } from "../i18n/I18nProvider";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => void;
}

export function ConfirmDialog({ open, title, description, confirmLabel, onCancel, onConfirm }: ConfirmDialogProps) {
  const { t } = useI18n();
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel, open]);

  if (!open) return null;
  return (
    <div className="dialog-backdrop">
      <div className="confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-description">
        <div className="dialog-icon"><AlertTriangle size={22} /></div>
        <div><h2 id="confirm-title">{title}</h2><p id="confirm-description">{description}</p></div>
        <div className="dialog-actions">
          <button ref={cancelRef} className="button button-secondary" type="button" onClick={onCancel}>{t("common.cancel")}</button>
          <button className="button button-danger" type="button" onClick={onConfirm}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}
