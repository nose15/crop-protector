// Przełącznik segmentowy „Tak | Nie” (styl 6.13). Ponowne kliknięcie zaznaczonej odpowiedzi zdejmuje ją („nie wiem”).
export default function Seg({ value, onChange, label }) {
  const pick = (v) => onChange(value === v ? null : v);
  return (
    <span className="seg" role="group" aria-label={label}>
      <button type="button" aria-pressed={value === true} onClick={() => pick(true)}>Tak</button>
      <button type="button" aria-pressed={value === false} onClick={() => pick(false)}>Nie</button>
    </span>
  );
}
