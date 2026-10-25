/**
 * Unit under test: `TableSort`, sorting a console table by a column.
 *
 * Why: the tables are how a maintainer finds the costly or slow step. A sort that puts missing values first, shuffles
 * ties on every click, or compares "10" before "9" as text sends them to the wrong row.
 *
 * Use cases:
 * - a new column starts in the first direction asked for, the same column turns round
 * - `aria-sort` is ascending or descending on the sorted column and none elsewhere
 * - numbers sort as numbers, text by locale with numbers inside it read as numbers
 * - rows with no value come last in both directions
 * - ties keep their order, and the input is not changed
 * - without a sort the rows keep their order
 */
import { describe, expect, test } from "bun:test";

import { TableSort, type SortState } from "./table-sort";

type Row = { name: string; spend: number | null };
const rows: Row[] = [
  { name: "step 10", spend: 2 },
  { name: "step 2", spend: null },
  { name: "step 9", spend: 5 },
  { name: "step 1", spend: 2 },
];
const value = (row: Row, key: string) => (key === "name" ? row.name : row.spend);
const names = (sorted: Row[]) => sorted.map((row) => row.name);

describe("TableSort.next", () => {
  test("a new column starts in the first direction", () => {
    expect(TableSort.next(null, "spend")).toEqual({ key: "spend", direction: "desc" });
    expect(TableSort.next({ key: "name", direction: "asc" }, "spend", "asc")).toEqual({ key: "spend", direction: "asc" });
  });

  test("the same column turns round", () => {
    const desc: SortState = { key: "spend", direction: "desc" };

    expect(TableSort.next(desc, "spend")).toEqual({ key: "spend", direction: "asc" });
    expect(TableSort.next(TableSort.next(desc, "spend"), "spend")).toEqual(desc);
  });
});

describe("TableSort.ariaSort", () => {
  test("names the sorted column and its direction", () => {
    const sort: SortState = { key: "spend", direction: "asc" };

    expect(TableSort.ariaSort(sort, "spend")).toBe("ascending");
    expect(TableSort.ariaSort({ ...sort, direction: "desc" }, "spend")).toBe("descending");
    expect(TableSort.ariaSort(sort, "name")).toBe("none");
    expect(TableSort.ariaSort(null, "name")).toBe("none");
  });
});

describe("TableSort.apply", () => {
  test("numbers sort as numbers, with missing values last either way", () => {
    expect(names(TableSort.apply(rows, { key: "spend", direction: "desc" }, value))).toEqual(["step 9", "step 10", "step 1", "step 2"]);
    expect(names(TableSort.apply(rows, { key: "spend", direction: "asc" }, value))).toEqual(["step 10", "step 1", "step 9", "step 2"]);
  });

  test("text sorts with the numbers in it read as numbers", () => {
    expect(names(TableSort.apply(rows, { key: "name", direction: "asc" }, value))).toEqual(["step 1", "step 2", "step 9", "step 10"]);
    expect(names(TableSort.apply(rows, { key: "name", direction: "desc" }, value))).toEqual(["step 10", "step 9", "step 2", "step 1"]);
  });

  test("ties keep their order, whichever way", () => {
    expect(names(TableSort.apply(rows, { key: "spend", direction: "asc" }, value)).slice(0, 2)).toEqual(["step 10", "step 1"]);
    expect(names(TableSort.apply(rows, { key: "spend", direction: "desc" }, value)).slice(1, 3)).toEqual(["step 10", "step 1"]);
  });

  test("no sort keeps the order, and nothing is changed in place", () => {
    const copy = [...rows];

    expect(TableSort.apply(rows, null, value)).toEqual(rows);
    TableSort.apply(rows, { key: "name", direction: "asc" }, value);
    expect(rows).toEqual(copy);
  });
});
