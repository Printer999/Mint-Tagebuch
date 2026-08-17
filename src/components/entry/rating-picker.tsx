"use client";

interface RatingPickerProps {
  value: number;
  onChange: (value: number) => void;
  disabled?: boolean;
}

const TITLES: Record<number, string> = {
  1: "1 – schwierig",
  2: "2 – eher schwach",
  3: "3 – gut",
  4: "4 – sehr gut",
  5: "5 – fantastisch",
};

/**
 * Star rating picker that recreates the original Mint Week control: the
 * stars up to the selected value are highlighted.
 */
export function RatingPicker({ value, onChange, disabled }: RatingPickerProps) {
  return (
    <div
      role="radiogroup"
      aria-label="Bewertung"
      className="flex flex-wrap items-center gap-1.5"
    >
      {[1, 2, 3, 4, 5].map((n) => {
        const selected = n <= value;
        return (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={n === value}
            aria-label={TITLES[n]}
            title={TITLES[n]}
            disabled={disabled}
            onClick={() => onChange(n)}
            className={[
              "grid h-9 w-9 place-items-center rounded-[10px] border text-xl leading-none transition",
              "select-none disabled:cursor-not-allowed",
              selected
                ? "border-[rgba(246,198,108,0.45)] bg-[rgba(246,198,108,0.12)] text-[#f6c66c]"
                : "border-[rgba(148,163,184,0.14)] bg-[rgba(148,163,184,0.06)] text-[#7a8493] hover:-translate-y-0.5 hover:border-[rgba(246,198,108,0.35)] hover:text-[#f6c66c]",
            ].join(" ")}
          >
            ★
          </button>
        );
      })}
      <span className="ml-1 text-sm font-semibold text-[#9bb4c7]">
        {value}/5
      </span>
    </div>
  );
}
