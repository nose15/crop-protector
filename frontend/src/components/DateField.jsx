// Pole daty po polsku: tekst dd.mm.rrrr i siatka miesiąca. W stanie zostaje ISO.
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { formatDate, parsePlDate } from "../lib/present.js";

const WEEKDAYS = [
  ["Pn", "poniedziałek"],
  ["Wt", "wtorek"],
  ["Śr", "środa"],
  ["Cz", "czwartek"],
  ["Pt", "piątek"],
  ["So", "sobota"],
  ["Nd", "niedziela"],
];

function toIso(year, month, day) {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function partsOf(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!m) return null;
  return { y: Number(m[1]), m: Number(m[2]), d: Number(m[3]) };
}

function addDays(iso, days) {
  const p = partsOf(iso);
  if (!p) return iso;
  const dt = new Date(p.y, p.m - 1, p.d + days);
  return toIso(dt.getFullYear(), dt.getMonth() + 1, dt.getDate());
}

function addMonths(iso, delta) {
  const p = partsOf(iso);
  if (!p) return iso;
  const first = new Date(p.y, p.m - 1 + delta, 1);
  const last = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  return toIso(first.getFullYear(), first.getMonth() + 1, Math.min(p.d, last));
}

function monthCells(year, month) {
  const lead = (new Date(year, month - 1, 1).getDay() + 6) % 7;
  const cells = [];
  for (let i = 0; i < 42; i++) {
    const dt = new Date(year, month - 1, 1 - lead + i);
    const y = dt.getFullYear();
    const m = dt.getMonth() + 1;
    const d = dt.getDate();
    cells.push({
      iso: toIso(y, m, d),
      day: d,
      outside: y !== year || m !== month,
    });
  }
  return cells;
}

function dayLabel(iso) {
  const p = partsOf(iso);
  if (!p) return iso;
  return new Intl.DateTimeFormat("pl-PL", {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  }).format(new Date(p.y, p.m - 1, p.d));
}

export default function DateField({ value, onChange, min, max, allowEmpty = false }) {
  const [text, setText] = useState(() => formatDate(value));
  const [open, setOpen] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  const [view, setView] = useState(() => {
    const p = partsOf(value);
    const now = new Date();
    return p ? { y: p.y, m: p.m } : { y: now.getFullYear(), m: now.getMonth() + 1 };
  });
  const [focusIso, setFocusIso] = useState(value || "");
  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const btnRef = useRef(null);
  const dialogRef = useRef(null);
  const skipBlur = useRef(false);
  const uid = useId();
  const dialogId = `${uid}-cal`;
  const titleId = `${uid}-title`;
  const labelId = `${uid}-lbl`;

  useLayoutEffect(() => {
    const span = rootRef.current?.parentElement?.querySelector(":scope > span");
    if (span) span.id = labelId;
  }, [labelId]);

  useEffect(() => {
    setText(formatDate(value));
  }, [value]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (dialogRef.current?.contains(e.target)) return;
      if (btnRef.current?.contains(e.target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useLayoutEffect(() => {
    if (!open || !rootRef.current || !dialogRef.current) return;
    const spaceRight = window.innerWidth - rootRef.current.getBoundingClientRect().left;
    setAlignRight(spaceRight < dialogRef.current.offsetWidth + 8);
  }, [open]);

  useEffect(() => {
    if (!open || !dialogRef.current) return;
    const el = dialogRef.current.querySelector(`[data-iso="${focusIso}"]`);
    if (el && !el.disabled) el.focus({ preventScroll: true });
    else dialogRef.current.focus({ preventScroll: true });
  }, [open, focusIso]);

  function within(iso) {
    if (!iso) return false;
    if (min && iso < min) return false;
    if (max && iso > max) return false;
    return true;
  }

  function applyText() {
    if (skipBlur.current) {
      skipBlur.current = false;
      return;
    }
    const raw = text.trim();
    if (raw === "") {
      if (allowEmpty) {
        onChange(null);
        setText("");
      } else {
        setText(formatDate(value));
      }
      return;
    }
    const iso = parsePlDate(raw);
    if (!iso || !within(iso)) {
      setText(formatDate(value));
      return;
    }
    setText(formatDate(iso));
    onChange(iso);
  }

  function select(iso) {
    if (!within(iso)) return;
    skipBlur.current = true;
    setText(formatDate(iso));
    onChange(iso);
    setOpen(false);
    btnRef.current?.focus();
    skipBlur.current = false;
  }

  function moveFocus(next) {
    const p = partsOf(next);
    if (!p) return;
    setFocusIso(next);
    setView({ y: p.y, m: p.m });
  }

  function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    const p = partsOf(value);
    const now = new Date();
    const y = p ? p.y : now.getFullYear();
    const m = p ? p.m : now.getMonth() + 1;
    const d = p ? p.d : now.getDate();
    setView({ y, m });
    setFocusIso(toIso(y, m, d));
    setOpen(true);
  }

  function onKeyDown(e) {
    if (e.key === "ArrowLeft") { e.preventDefault(); moveFocus(addDays(focusIso, -1)); }
    else if (e.key === "ArrowRight") { e.preventDefault(); moveFocus(addDays(focusIso, 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); moveFocus(addDays(focusIso, -7)); }
    else if (e.key === "ArrowDown") { e.preventDefault(); moveFocus(addDays(focusIso, 7)); }
    else if (e.key === "PageUp") { e.preventDefault(); moveFocus(addMonths(focusIso, -1)); }
    else if (e.key === "PageDown") { e.preventDefault(); moveFocus(addMonths(focusIso, 1)); }
    else if (e.key === "Enter") {
      e.preventDefault();
      if (within(focusIso)) select(focusIso);
    } else if (e.key === "Escape") {
      e.preventDefault();
      skipBlur.current = true;
      setText(formatDate(value));
      setOpen(false);
      btnRef.current?.focus();
      skipBlur.current = false;
    }
  }

  const title = new Intl.DateTimeFormat("pl-PL", { month: "long", year: "numeric" })
    .format(new Date(view.y, view.m - 1, 1));
  const cells = monthCells(view.y, view.m);
  const weeks = [0, 1, 2, 3, 4, 5].map((i) => cells.slice(i * 7, i * 7 + 7));

  return (
    <div className={`datefield${open ? " open" : ""}`} ref={rootRef}>
      <input
        ref={inputRef}
        type="text"
        inputMode="numeric"
        autoComplete="off"
        spellCheck={false}
        aria-labelledby={labelId}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={applyText}
        onKeyDown={(e) => {
          if (e.key === "Enter") applyText();
          else if (e.key === "Escape" && open) {
            e.preventDefault();
            e.stopPropagation();
            skipBlur.current = true;
            setText(formatDate(value));
            setOpen(false);
            btnRef.current?.focus();
            skipBlur.current = false;
          }
        }}
      />
      <button
        type="button"
        className="datebtn"
        ref={btnRef}
        aria-label="Otwórz kalendarz"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-controls={open ? dialogId : undefined}
        onClick={toggle}
      >
        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
          <rect x="2" y="3" width="12" height="11" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <path d="M2 6.5h12M5 2.2v2.4M11 2.2v2.4" stroke="currentColor" strokeWidth="1.4" fill="none" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div
          className={`datepop${alignRight ? " right" : ""}`}
          id={dialogId}
          role="dialog"
          aria-modal="false"
          aria-labelledby={titleId}
          tabIndex={-1}
          ref={dialogRef}
          onKeyDown={onKeyDown}
          onMouseDown={(e) => e.preventDefault()}
        >
          <div className="datepop-head">
            <button type="button" aria-label="Poprzedni miesiąc" onClick={() => moveFocus(addMonths(focusIso, -1))}>‹</button>
            <span id={titleId}>{title}</span>
            <button type="button" aria-label="Następny miesiąc" onClick={() => moveFocus(addMonths(focusIso, 1))}>›</button>
          </div>
          <table className="dategrid">
            <thead>
              <tr>
                {WEEKDAYS.map(([short, long]) => (
                  <th key={short} scope="col" title={long}>
                    <span aria-hidden="true">{short}</span>
                    <span className="sr-only">{long}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {weeks.map((week) => (
                <tr key={week[0].iso}>
                  {week.map((cell) => {
                    const enabled = within(cell.iso);
                    const pressed = cell.iso === value;
                    return (
                      <td key={cell.iso}>
                        <button
                          type="button"
                          data-iso={cell.iso}
                          className={`${cell.outside ? "outside" : ""}${cell.iso === focusIso ? " is-cursor" : ""}`}
                          disabled={!enabled}
                          aria-pressed={pressed ? "true" : undefined}
                          aria-label={dayLabel(cell.iso)}
                          onClick={() => select(cell.iso)}
                        >
                          {cell.day}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
