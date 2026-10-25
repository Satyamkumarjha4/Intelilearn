export type SortDirection = "asc" | "desc";
export type SortState = { key: string; direction: SortDirection };
export type SortValue = string | number | null | undefined;

/** Sorting a table by a column: which way next, the `aria-sort` word, and the sorted rows. */
export class TableSort {
  /** A click on a column: a new column starts in `first` direction, the same column turns round. */
  static next(current: SortState | null, key: string, first: SortDirection = "desc"): SortState {
    if (current?.key !== key) return { key, direction: first };
    return { key, direction: current.direction === "asc" ? "desc" : "asc" };
  }

  static ariaSort(current: SortState | null, key: string): "ascending" | "descending" | "none" {
    if (current?.key !== key) return "none";
    return current.direction === "asc" ? "ascending" : "descending";
  }

  /**
   * The rows in order of the column `current` names, read from each row by `value`. Text is compared by locale with
   * numbers in it read as numbers ("step 2" before "step 10"); rows with nothing to compare go last whichever way it
   * runs; ties keep their order.
   */
  static apply<T>(rows: readonly T[], current: SortState | null, value: (row: T, key: string) => SortValue): T[] {
    if (!current) return [...rows];
    const sign = current.direction === "asc" ? 1 : -1;
    const indexed = rows.map((row, index) => ({ row, index, cell: value(row, current.key) }));
    indexed.sort((a, b) => {
      const aEmpty = a.cell === null || a.cell === undefined;
      const bEmpty = b.cell === null || b.cell === undefined;
      if (aEmpty || bEmpty) return aEmpty === bEmpty ? a.index - b.index : aEmpty ? 1 : -1;
      const order =
        typeof a.cell === "number" && typeof b.cell === "number"
          ? a.cell - b.cell
          : String(a.cell).localeCompare(String(b.cell), "en", { numeric: true });
      return order === 0 ? a.index - b.index : sign * order;
    });
    return indexed.map((entry) => entry.row);
  }
}
