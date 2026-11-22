// Własne, proste ikony SVG (styl „Pole z lotu ptaka”, rozdz. 6.17). Dekoracyjne: znaczenie zawsze niesie tekst obok.

export function BrandMark() {
  return (
    <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true">
      <path d="M16 3c4.8 5.8 8.7 10.6 8.7 15.2A8.7 8.7 0 0 1 7.3 18.2C7.3 13.6 11.2 8.8 16 3Z" fill="#1F6FA8" />
      <path d="M7 24.5c3-1.6 6-1.6 9 0s6 1.6 9 0" stroke="#2F6B3B" strokeWidth="2.4" fill="none" strokeLinecap="round" />
    </svg>
  );
}

export function StatusIcon({ level }) {
  const common = { viewBox: "0 0 20 20", width: 20, height: 20, "aria-hidden": true };
  if (level === "alarm")
    return <svg {...common}><path d="M10 1.8 19 17.6H1Z" fill="currentColor" /><path d="M10 7.2v5M10 14.6v.3" stroke="#fff" strokeWidth="2" strokeLinecap="round" /></svg>;
  if (level === "ok")
    return <svg {...common}><circle cx="10" cy="10" r="8.5" fill="currentColor" /><path d="M6 10.4 8.8 13 14 7.4" stroke="#fff" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" /></svg>;
  if (level === "info")
    return <svg {...common}><circle cx="10" cy="10" r="8.5" fill="currentColor" /><path d="M10 9v5M10 6.2v.3" stroke="#fff" strokeWidth="2" strokeLinecap="round" /></svg>;
  return <svg {...common}><circle cx="10" cy="10" r="8.5" fill="currentColor" /><path d="M10 5.5v5.5M10 13.8v.3" stroke="#fff" strokeWidth="2" strokeLinecap="round" /></svg>;
}

export function CauseIcon({ code }) {
  const common = { viewBox: "0 0 24 24", width: 22, height: 22, "aria-hidden": true };
  if (code === "C1")
    return (
      <svg {...common}>
        <circle cx="9" cy="9" r="4.2" fill="#E3A51C" />
        <path d="M9 1.8v2M9 14.2v2M1.8 9h2M14.2 9h2M3.9 3.9l1.4 1.4M12.7 12.7l1.4 1.4M3.9 14.1l1.4-1.4M12.7 5.3l1.4-1.4" stroke="#E3A51C" strokeWidth="1.6" strokeLinecap="round" />
        <path d="M10 20.5h9.5a3.2 3.2 0 0 0 0-6.4 4.4 4.4 0 0 0-8.5 1A2.7 2.7 0 0 0 10 20.5Z" fill="#9AA79F" />
      </svg>
    );
  if (code === "C2")
    return (
      <svg {...common}>
        <rect x="2" y="12" width="20" height="4" rx="1" fill="#B98B55" />
        <rect x="2" y="16.5" width="20" height="5" rx="1" fill="#6C4E2B" />
        <path d="M12 2.5c2 2.4 3.6 4.4 3.6 6.3a3.6 3.6 0 0 1-7.2 0c0-1.9 1.6-3.9 3.6-6.3Z" fill="#1F6FA8" />
      </svg>
    );
  if (code === "C3")
    return (
      <svg {...common}>
        <path d="M2 20.5 22 9v11.5Z" fill="#8FB47A" />
        <path d="M5 8.5c3 0 6 1.5 9 4.5" stroke="#1F6FA8" strokeWidth="2" fill="none" strokeLinecap="round" />
        <path d="M14.6 9.6 14 13l-3.3-.9" stroke="#1F6FA8" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  return (
    <svg {...common}>
      <path d="M12 22V9" stroke="#2F6B3B" strokeWidth="1.8" strokeLinecap="round" />
      {[0, 1, 2].map((i) => (
        <g key={i}>
          <ellipse cx="9.6" cy={6 + i * 4} rx="2" ry="3.4" transform={`rotate(-28 9.6 ${6 + i * 4})`} fill="#D9A21B" />
          <ellipse cx="14.4" cy={6 + i * 4} rx="2" ry="3.4" transform={`rotate(28 14.4 ${6 + i * 4})`} fill="#D9A21B" />
        </g>
      ))}
    </svg>
  );
}

export function ContrastIcon() {
  return (
    <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
      <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="M10 2a8 8 0 0 1 0 16Z" fill="currentColor" />
    </svg>
  );
}
