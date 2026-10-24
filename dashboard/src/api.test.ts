import { describe, expect, it } from "vitest";
import { cohortGrid, emptyFilters, toQuery } from "./api";

describe("toQuery", () => {
  it("omits empty filters", () => {
    expect(toQuery(emptyFilters)).toBe("");
  });

  it("repeats list keys and appends extras", () => {
    const query = toQuery(
      { ...emptyFilters, start: "2025-07-01", category: ["Books", "Home & Garden"] },
      { limit: 25 },
    );
    expect(query).toBe("?start=2025-07-01&category=Books&category=Home+%26+Garden&limit=25");
  });
});

describe("cohortGrid", () => {
  it("pads missing offsets with null", () => {
    const grid = cohortGrid([
      { cohort: "2025-07", size: 4, retention: [{ offset: 0, customers: 4, rate: 1 }, { offset: 2, customers: 1, rate: 0.25 }] },
      { cohort: "2025-08", size: 2, retention: [{ offset: 0, customers: 2, rate: 1 }] },
    ]);
    expect(grid.width).toBe(3);
    expect(grid.rows).toEqual([[1, null, 0.25], [1, null, null]]);
  });
});
