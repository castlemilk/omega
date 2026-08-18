/**
 * The version picker, shared by every view that is scoped to one training run.
 *
 * It is a free-text input backed by a `<datalist>`, not a `<select>`, for a
 * reason the data forces: `/api/v1/training/versions` answers **586 rows**, and
 * a 586-option select is unusable while a typeahead over the same list is not.
 * Free text also keeps versions reachable that the ledger does not list — the
 * gate and decision-trace corpora are not subsets of the results corpus (102
 * decision-trace files, 100 of them in `/versions`; 280 gate files, on a
 * different naming era entirely), so a picker that could only offer what
 * `/versions` returns would hide real data.
 *
 * The ledger is loaded through the same hook the Runs view uses. If it fails,
 * the input still works — a picker that dies with its suggestion list would take
 * the whole view with it, and the version can always be typed.
 */
import { useMemo } from 'react';
import { useVictoriaVersions } from '../hooks.js';
import { sortVersions } from './Runs.js';

/** How many suggestions to emit. The full 586 make a heavy datalist for no gain. */
const MAX_SUGGESTIONS = 200;

export function VersionPicker({
  value,
  onChange,
  listId,
  placeholder = 'version…',
  ariaLabel = 'Version',
}: {
  value: string;
  onChange: (version: string) => void;
  /** Must be unique per rendered picker — it is a DOM id. */
  listId: string;
  placeholder?: string;
  ariaLabel?: string;
}) {
  const versions = useVictoriaVersions();
  const options = useMemo(
    () => sortVersions(versions.data ?? []).slice(0, MAX_SUGGESTIONS),
    [versions.data],
  );

  return (
    <span className="flex items-center gap-2">
      <input
        value={value}
        onChange={(e) => { onChange(e.target.value); }}
        list={listId}
        placeholder={placeholder}
        aria-label={ariaLabel}
        className="w-56 rounded-md border border-line bg-control px-2.5 py-1.5 font-mono text-[10.5px] text-ink placeholder:text-ghost focus:border-edge focus:outline-none"
      />
      <datalist id={listId}>
        {options.map((v, i) => (
          // Keyed on position: `/versions` labels are not unique — two results
          // files in the omega data directory both declare "v10".
          <option key={`${v.version}-${String(i)}`} value={v.version} />
        ))}
      </datalist>
      {value !== '' && (
        <button
          type="button"
          onClick={() => { onChange(''); }}
          className="font-mono text-[9.5px] text-faint hover:text-ink3"
        >
          clear
        </button>
      )}
    </span>
  );
}
