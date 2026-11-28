import { memo } from "react";
import { useRowDrag, RowGrip, Editable } from "millwork";

// A song is drawn again when the song itself changes, and not when another
// one is renamed or moved.
const Song = memo(function Song({ song, row, grip, emit }) {
  return (
    <li {...row} className="flex items-center gap-2 rounded-lg border bg-card px-2 py-1.5 text-sm">
      <RowGrip {...grip} label={`Move ${song.title}`} />
      <div className="min-w-0 grow">
        <Editable
          value={song.title}
          label="Title"
          placeholder="No title"
          onCommit={(title) => emit("rename", { key: song.key, title })}
        />
      </div>
      <span className="text-muted-foreground tabular-nums">{song.length}</span>
    </li>
  );
});

export default function Setlist({ props, emit }) {
  const songs = new Map(props.songs.map((song) => [song.key, song]));
  const drag = useRowDrag({
    keys: props.songs.map((song) => song.key),
    onMove: (key, to) => emit("move", { key, to }),
  });
  return (
    <ol ref={drag.list} className="flex max-w-md flex-col gap-1.5">
      {drag.order.map((key) => (
        <Song key={key} song={songs.get(key)} row={drag.row(key)} grip={drag.grip(key)} emit={emit} />
      ))}
    </ol>
  );
}
