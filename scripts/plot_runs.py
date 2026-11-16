"""Plot how training runs improve: win rate and clean-win rate against decisions trained.

  python scripts/plot_runs.py runs/pilot_check runs/pilot_check2 --baseline-win 0.61 --baseline-clean 0.37
  python scripts/plot_runs.py runs/pilot --by-battle [--metric win]

Each run is a --run-dir of scripts/train_ppo.py; its metrics.jsonl has one line per update.
The line is the mean of the last 3 updates and the dots are each update's own value, which is
noisy: an update sees about 100 episodes spread over every battle. --state limits the plot to
one battle. --return adds a return panel, but returns compare only between runs with the same
reward. The random-play baselines are reference lines when given.

--by-battle draws a heatmap per run instead: a row per battle, a column per --bin updates, and
the clean-win rate (or another --metric) of the episodes in that stretch, darker for higher.
Each row ends with its first and last values. --metric length shows decisions per episode,
where a battle stuck at 1 means no decision matters; --metric dry, moves run out of PP per
episode.

--view picks the other charts, all against decisions trained:
  health  entropy, KL, clip fraction, explained variance, value loss, throughput, CPU
          temperature, and the episodes that need a look (STUCK, TURN_CAP or ENDED, or a
          WON or LOST the game's own result contradicts), runs overlaid
  faints  per battle, faints per episode of the team's strongest Pokémon and of the others
  picks   per battle, the share of decisions by kind: an attack by its type matchup, a
          status move, a switch, a forced switch, or Struggle
  moves   per battle, a heatmap of the share of decisions that used each move or switched
The per-battle views take the first run only. Writes --out (a PNG).
"""
import argparse, collections, json, os, sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The dataviz reference palette, light mode: categorical slots in their fixed order, and chrome.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SURFACE, INK, INK_2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
# The reference sequential blue, steps 100 to 700, light (low) to dark (high); EMPTY is a cell with no episodes.
RAMP = ("#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf",
        "#1c5cab", "#184f95", "#104281", "#0d366b")
EMPTY = "#f0efec"
WINDOW = 3
# --metric: (label, the value of one state's row, the heatmap's top value or None for the data's own)
METRICS = {"clean": ("Clean-win rate (won with no faint)", lambda s: s.get("clean_win_rate"), 1),
           "win": ("Win rate", lambda s: s.get("win_rate"), 1),
           "length": ("Decisions per episode", lambda s: s.get("mean_length"), None),
           "dry": ("Moves run out of PP per episode",
                   lambda s: s["pp_ran_dry"] / s["episodes"] if "pp_ran_dry" in s else None, None)}
# Decision kinds, in the order they stack: attacks from best matchup to worst, then the rest.
PICKS = ("super", "neutral", "resisted", "immune", "status", "switch", "forced_switch", "struggle")


def load(run_dir: str, state: str | None) -> list[dict]:
    """One {decisions, win_rate, clean_win_rate, mean_return} per update, for the whole run or one battle."""
    rows = []
    with open(os.path.join(run_dir, "metrics.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            s = r if state is None else r["states"].get(state if state.endswith(".state") else state + ".state")
            if s and s.get("episodes"):
                rows.append({"decisions": r["decisions"], "win_rate": s.get("win_rate"),
                             "clean_win_rate": s.get("clean_win_rate"), "mean_return": s.get("mean_return")})
    return rows


def rolling(values: list[float]) -> list[float]:
    return [sum(values[max(0, i - WINDOW + 1):i + 1]) / len(values[max(0, i - WINDOW + 1):i + 1])
            for i in range(len(values))]


def label_ends(ax, ends: list[tuple[float, float, str]], fmt):
    """Label each line's last point in a column right of the plot, run name and value in ink, with
    a thin leader line back to the point. Labels are spread apart only where lines end close
    together, so each stays readable and still points at its own line."""
    lo, hi = ax.get_ylim()
    gap = 0.07 * (hi - lo)
    placed = []
    for x, y, name in sorted(ends, key=lambda e: e[1]):
        placed.append((x, y, name, max(y, placed[-1][3] + gap) if placed else y))
    for x, y, name, y_label in placed:
        ax.annotate(f"{name}  {fmt(y)}", (x, y), xytext=(1.02, y_label), textcoords=("axes fraction", "data"),
                    va="center", color=INK_2, fontsize=9, annotation_clip=False,
                    arrowprops=dict(arrowstyle="-", color=AXIS, linewidth=0.8, shrinkA=0, shrinkB=3))


KILO = matplotlib.ticker.FuncFormatter(lambda x, _: f"{x / 1000:g}k" if x else "0")


def read_rows(run_dir: str) -> list[dict]:
    with open(os.path.join(run_dir, "metrics.jsonl")) as f:
        return [json.loads(line) for line in f]


def bins_of(rows: list[dict], bin_updates: int) -> list[list[dict]]:
    return [rows[i:i + bin_updates] for i in range(0, len(rows), bin_updates)]


def battle_grid(run_dir: str, value, bin_updates: int):
    """(battles, decisions at the end of each bin, grid[battle][bin]) for one run. A cell is
    value(a state's row), a per-episode number, pooled over every episode of that battle in
    the bin; None where the battle had none, or value is None (a run from before the field)."""
    rows = read_rows(run_dir)
    battles = sorted({st for r in rows for st in r["states"]})
    bins = bins_of(rows, bin_updates)
    grid = []
    for battle in battles:
        cells = []
        for b in bins:
            stats = [(value(r["states"][battle]), r["states"][battle]["episodes"]) for r in b if battle in r["states"]]
            stats = [(v, n) for v, n in stats if v is not None]
            n = sum(n for _, n in stats)
            cells.append(sum(v * k for v, k in stats) / n if n else None)
        grid.append(cells)
    return [b.removesuffix(".state") for b in battles], [b[-1]["decisions"] for b in bins], grid


def binned_counts(rows: list[dict], battle: str, field: str, bin_updates: int) -> list[collections.Counter]:
    """For one battle, the counts in its rows' `field` (picks or moves) summed over each bin."""
    return [sum((collections.Counter(r["states"].get(battle, {}).get(field, {})) for r in b), collections.Counter())
            for b in bins_of(rows, bin_updates)]


def ramp_cmap():
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list("ramp", RAMP)
    cmap.set_bad(EMPTY)
    return cmap


def style(ax, title: str):
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=10, pad=6)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.xaxis.set_major_formatter(KILO)


def battle_axes(n: int, title: str, height: float = 2.6, sharey: bool = True):
    """A grid of small panels, one per battle, five across, sharing the x axis and, unless
    told not to, the y axis."""
    cols = min(5, n)
    rows = -(-n // cols)
    fig, axes = plt.subplots(rows, cols, figsize=(3.3 * cols, height * rows + 1.2), sharex=True, sharey=sharey,
                             facecolor=SURFACE, squeeze=False)
    for ax in axes.flat[n:]:
        ax.set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel("Decisions trained")
    fig.suptitle(title, x=0.01, ha="left", color=INK, fontsize=13, fontweight="bold")
    return fig, list(axes.flat[:n])


def by_battle(args):
    label, value, top = METRICS[args.metric]
    runs = [(os.path.basename(os.path.normpath(r)), *battle_grid(r, value, args.bin)) for r in args.runs]
    runs = [r for r in runs if any(v is not None for row in r[3] for v in row)]
    if not runs:
        sys.exit(f"no run has --metric {args.metric}; it came with later logging")
    top = top or max(v for r in runs for row in r[3] for v in row if v is not None) or 1
    fmt = (lambda v: f"{v:.2f}") if args.metric in ("clean", "win") else (lambda v: f"{v:.1f}")
    cmap = ramp_cmap()
    heights = [len(r[1]) for r in runs]
    fig, axes = plt.subplots(len(runs), 1, figsize=(10, 0.36 * sum(heights) + 1.6 * len(runs) + 0.6), sharex=True,
                             facecolor=SURFACE, squeeze=False, gridspec_kw={"height_ratios": heights})
    for ax, (name, battles, ends, grid) in zip(axes[:, 0], runs):
        values = [[float("nan") if v is None else v for v in row] for row in grid]
        # Columns span the decisions they cover, so runs line up on one scale.
        mesh = ax.pcolormesh([0] + ends, range(len(battles) + 1), values, cmap=cmap, vmin=0, vmax=top,
                             edgecolors=SURFACE, linewidth=2)
        ax.set_facecolor(SURFACE)
        ax.set_title(name, loc="left", color=INK, fontsize=11, pad=8)
        ax.set_yticks([i + 0.5 for i in range(len(battles))], [b.replace("_", " ") for b in battles], color=INK_2)
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(KILO)
        ax.set_xlabel(f"Decisions trained (each column is {args.bin} updates)")
        ax.xaxis.set_tick_params(labelbottom=True)
        ax.tick_params(length=0)
        for side in ax.spines.values():
            side.set_visible(False)
        for i, row in enumerate(grid):
            seen = [v for v in row if v is not None]
            if seen:
                ax.annotate(f"{fmt(seen[0])} → {fmt(seen[-1])}", (1, i + 0.5), xycoords=("axes fraction", "data"),
                            xytext=(8, 0), textcoords="offset points", va="center", color=INK_2, fontsize=9)
    bar = fig.colorbar(mesh, ax=axes[:, 0], location="bottom", shrink=0.4, aspect=30, pad=0.12)
    bar.set_label(label, color=INK_2)
    bar.outline.set_visible(False)
    fig.suptitle(f"{label} by battle", x=0.01, ha="left", color=INK, fontsize=13, fontweight="bold")
    return fig


HEALTH = (("entropy", "Entropy"), ("approx_kl", "Approximate KL"), ("clip_frac", "Clip fraction"),
          ("explained_variance", "Explained variance"), ("value_loss", "Value loss"),
          ("decisions_per_s", "Decisions per second"), ("cpu_temp", "CPU temperature (°C)"),
          ("needs_look", "Episodes to look at (should stay 0)"))


def needs_look(r: dict) -> int:
    """Episodes that ended STUCK, TURN_CAP or ENDED, or whose WON or LOST the game contradicts."""
    return sum(v for k, v in r.get("outcomes", {}).items() if k not in ("WON", "LOST")) + r.get("result_mismatches", 0)


def health(args):
    if len(args.runs) > len(SERIES):
        sys.exit(f"at most {len(SERIES)} runs per chart")
    runs = [(os.path.basename(os.path.normpath(r)), read_rows(r)) for r in args.runs]
    fig, axes = plt.subplots(2, 4, figsize=(16, 6.6), sharex=True, facecolor=SURFACE)
    for ax, (key, title) in zip(axes.flat, HEALTH):
        style(ax, title)
        for color, (name, rows) in zip(SERIES, runs):
            pts = [(r["decisions"], needs_look(r) if key == "needs_look" else r.get(key)) for r in rows]
            pts = [(x, y) for x, y in pts if y is not None]
            if not pts:
                continue
            xs, ys = zip(*pts)
            ax.plot(xs, ys, "o", color=color, markersize=3, alpha=0.35, markeredgewidth=0)
            ax.plot(xs, rolling(list(ys)), color=color, linewidth=2, solid_capstyle="round", label=name)
    for ax in axes[-1]:
        ax.set_xlabel("Decisions trained")
    if len(runs) > 1:
        fig.legend(*axes[0][0].get_legend_handles_labels(), loc="upper right", ncol=len(runs), frameon=False,
                   labelcolor=INK)
    fig.suptitle("Training health", x=0.01, ha="left", color=INK, fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    return fig


def faints(args):
    run = args.runs[0]
    battles, ends, ace = battle_grid(run, lambda s: s.get("mean_ace_faints"), args.bin)
    _, _, other = battle_grid(run, lambda s: s.get("mean_other_faints"), args.bin)
    if not any(v is not None for row in ace for v in row):
        sys.exit("this run has no ace and other faints; they came with later logging")
    fig, axes = battle_axes(len(battles), f"Faints per episode: the strongest Pokémon and the rest  ({os.path.basename(os.path.normpath(run))})")
    for ax, battle, a, o in zip(axes, battles, ace, other):
        style(ax, battle.replace("_", " "))
        for values, color, name in ((a, SERIES[0], "strongest"), (o, SERIES[1], "the others")):
            pts = [(x, v) for x, v in zip(ends, values) if v is not None]
            if pts:
                ax.plot(*zip(*pts), color=color, linewidth=2, solid_capstyle="round", label=name)
    axes[0].set_ylim(bottom=0)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper right", ncol=2, frameon=False, labelcolor=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig


def picks(args):
    run = args.runs[0]
    rows = read_rows(run)
    battles = sorted({st for r in rows for st in r["states"]})
    ends = [b[-1]["decisions"] for b in bins_of(rows, args.bin)]
    fig, axes = battle_axes(len(battles), f"Decisions by kind  ({os.path.basename(os.path.normpath(run))})")
    for ax, battle in zip(axes, battles):
        style(ax, battle.removesuffix(".state").replace("_", " "))
        counts = binned_counts(rows, battle, "picks", args.bin)
        shares = [[c[k] / max(sum(c.values()), 1) for c in counts] for k in PICKS]
        ax.stackplot(ends, shares, colors=SERIES[:len(PICKS)], labels=[k.replace("_", " ") for k in PICKS],
                     edgecolor=SURFACE, linewidth=1)
    if not any(sum(binned_counts(rows, b, "picks", args.bin), collections.Counter()) for b in battles):
        sys.exit("this run has no decision kinds; they came with later logging")
    axes[0].set_ylim(0, 1)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper right", ncol=len(PICKS), frameon=False,
               labelcolor=INK, fontsize=9)
    fig.tight_layout(rect=(0, 0, 1, 0.92))
    return fig


def moves(args):
    run = args.runs[0]
    rows = read_rows(run)
    battles = sorted({st for r in rows for st in r["states"]})
    ends = [b[-1]["decisions"] for b in bins_of(rows, args.bin)]
    cmap = ramp_cmap()
    fig, axes = battle_axes(len(battles), f"Share of each battle's decisions, by move  ({os.path.basename(os.path.normpath(run))})",
                            height=3.2, sharey=False)
    mesh = None
    for ax, battle in zip(axes, battles):
        moves_ = binned_counts(rows, battle, "moves", args.bin)
        kinds = binned_counts(rows, battle, "picks", args.bin)
        total = sum(moves_, collections.Counter())
        names = [m for m, _ in total.most_common()] + ["switch"]
        grid = [[(k["switch"] + k["forced_switch"] if m == "switch" else c[m]) / sum(k.values()) if sum(k.values()) else float("nan")
                 for c, k in zip(moves_, kinds)] for m in names]
        mesh = ax.pcolormesh([0] + ends, range(len(names) + 1), grid, cmap=cmap, vmin=0, vmax=1,
                             edgecolors=SURFACE, linewidth=1)
        ax.set_facecolor(SURFACE)
        ax.set_title(battle.removesuffix(".state").replace("_", " "), loc="left", color=INK, fontsize=10, pad=6)
        ax.set_yticks([i + 0.5 for i in range(len(names))], names, color=INK_2, fontsize=8)
        ax.tick_params(length=0, labelleft=True)
        ax.xaxis.set_major_formatter(KILO)
        for side in ax.spines.values():
            side.set_visible(False)
    if mesh is None or not any(sum(binned_counts(rows, b, "moves", args.bin), collections.Counter()) for b in battles):
        sys.exit("this run has no moves; they came with later logging")
    for ax in axes:
        ax.invert_yaxis()
    fig.tight_layout(rect=(0, 0.06, 1, 0.94))
    bar = fig.colorbar(mesh, ax=axes, location="bottom", shrink=0.3, aspect=30, pad=0.08)
    bar.set_label("Share of the battle's decisions", color=INK_2)
    bar.outline.set_visible(False)
    return fig


def lines(args):
    if len(args.runs) > len(SERIES):
        sys.exit(f"at most {len(SERIES)} runs per chart")
    panels = [("win_rate", "Win rate", args.baseline_win), ("clean_win_rate", "Clean-win rate (won with no faint)", args.baseline_clean)]
    if args.with_return:
        panels.append(("mean_return", "Return (compare only runs with the same reward)", args.baseline_return))
    fig, axes = plt.subplots(1, len(panels), figsize=(6.4 * len(panels), 4.0), facecolor=SURFACE, squeeze=False)
    runs = [(os.path.basename(os.path.normpath(r)), load(r, args.state)) for r in args.runs]

    for ax, (key, title, baseline) in zip(axes[0], panels):
        ax.set_facecolor(SURFACE)
        ax.set_title(title, loc="left", color=INK, fontsize=11, pad=10)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.set_xlabel("Decisions trained")
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x / 1000:g}k" if x else "0"))
        if key != "mean_return":
            ax.set_ylim(0, 1)
        fmt = (lambda v: f"{v:.2f}") if key != "mean_return" else (lambda v: f"{v:+.1f}")
        ends = []
        for color, (name, rows) in zip(SERIES, runs):
            pts = [(r["decisions"], r[key]) for r in rows if r[key] is not None]
            if not pts:
                continue        # this run predates the metric (clean wins came with faint counting)
            xs, ys = zip(*pts)
            ax.plot(xs, ys, "o", color=color, markersize=4, alpha=0.35, markeredgewidth=0)
            mean = rolling(list(ys))
            ax.plot(xs, mean, color=color, linewidth=2, solid_capstyle="round", solid_joinstyle="round", label=name)
            ends.append((xs[-1], mean[-1], name))
        if baseline is not None:
            ax.axhline(baseline, color=MUTED, linewidth=1.2, linestyle=(0, (4, 3)))
            # At the right end, under the line: the runs start beside random play and end above it.
            ax.annotate(f"random play {baseline:.2f}" if key != "mean_return" else f"random play {baseline:+.1f}",
                        (1, baseline), xycoords=("axes fraction", "data"), xytext=(-4, -4), textcoords="offset points",
                        ha="right", va="top", color=INK_2, fontsize=9)
        label_ends(ax, ends, fmt)
    if len(runs) > 1:
        fig.legend(*axes[0][0].get_legend_handles_labels(), loc="upper right", ncol=len(runs), frameon=False,
                   labelcolor=INK)
    fig.suptitle("Training progress" + (f": {args.state}" if args.state else ""), x=0.01, ha="left", color=INK,
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.subplots_adjust(wspace=0.45)       # room for the end labels between panels
    return fig


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+", help="run directories, each with a metrics.jsonl")
    ap.add_argument("--state", help="one battle's numbers, such as weak_lead_vs_lileep")
    ap.add_argument("--baseline-win", type=float, help="random play's win rate, drawn as a reference line")
    ap.add_argument("--baseline-clean", type=float, help="random play's clean-win rate")
    ap.add_argument("--baseline-return", type=float, help="random play's return, with --return")
    ap.add_argument("--return", dest="with_return", action="store_true", help="add a return panel")
    ap.add_argument("--by-battle", action="store_true", help="a heatmap per run: battles against training time")
    ap.add_argument("--view", choices=("health", "faints", "picks", "moves"), help="another chart; see above")
    ap.add_argument("--metric", choices=METRICS, default="clean", help="the heatmap's rate")
    ap.add_argument("--bin", type=int, default=5, help="updates per heatmap column")
    ap.add_argument("--out", default=os.path.join(ROOT, "runs", "progress.png"))
    args = ap.parse_args()
    plt.rcParams.update({"font.family": "sans-serif", "font.size": 10, "text.color": INK, "axes.labelcolor": INK_2,
                         "xtick.color": MUTED, "ytick.color": MUTED, "axes.edgecolor": AXIS})
    views = {"health": health, "faints": faints, "picks": picks, "moves": moves}
    fig = views[args.view](args) if args.view else by_battle(args) if args.by_battle else lines(args)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    fig.savefig(args.out, dpi=130, facecolor=SURFACE, bbox_inches="tight")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
