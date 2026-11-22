import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

export default function OverlayFrame({ label, onClose, children }) {
  const closeRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    closeRef.current?.focus();
    const esc = (e) => { if (e.key === "Escape") onCloseRef.current(); };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, []);

  return createPortal(
    <section className="overlay" role="dialog" aria-modal="true" aria-label={label}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="ov-inner">
        <button type="button" className="ov-close" ref={closeRef} aria-label="Zamknij" onClick={onClose}>×</button>
        {children}
      </div>
    </section>,
    document.body,
  );
}
