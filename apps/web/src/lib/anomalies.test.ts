import { describe, expect, it } from "vitest";

import { anomalies, anomaly, newKeyAnomaly, orgAnomaly } from "@/test/fixtures";

import { anomalyMarkers } from "./anomalies";

describe("anomalyMarkers", () => {
  it("groups the open anomalies into one marker per day, largest impact first", () => {
    const markers = anomalyMarkers(anomalies.anomalies);

    expect(markers.map((m) => m.day)).toEqual(["2026-08-09", "2026-08-11"]);
    const [keyDay, orgDay] = markers;
    // A workspace or key anomaly alone still marks its day, with the smaller dot.
    expect(keyDay).toEqual({
      day: "2026-08-09",
      endDay: "2026-08-09",
      kind: "open",
      label: "1 anomaly: experiment",
      note: "experiment +58.47",
      impact: "58.47",
      radius: 3,
      emphasis: "secondary",
      count: 1,
      href: "/anomalies/9",
    });
    // The organization total is off its baseline: larger dot, contributors by impact.
    expect(orgDay!.radius).toBe(5);
    expect(orgDay!.impact).toBe("900.00");
    expect(orgDay!.href).toBe("/anomalies");
    expect(orgDay!.label).toBe("2 anomalies");
    expect(orgDay!.note).toBe("organization total +900.00; ana@example.com +810.00");
    expect(orgDay!.emphasis).toBe("primary");
    expect(orgDay!.count).toBe(2);
  });

  it("names the top three contributors and marks the rest with an ellipsis", () => {
    const day = "2026-08-11";
    const extra = [
      {
        ...anomaly,
        id: 21,
        series_id: "w2",
        label: "Search (w2)",
        impact: "300.00",
        total_impact: "300.00",
      },
      {
        ...anomaly,
        id: 22,
        series_id: "w3",
        label: "Batch (w3)",
        impact: "20.00",
        total_impact: "20.00",
      },
    ];
    const [marker] = anomalyMarkers([orgAnomaly, anomaly, ...extra, { ...newKeyAnomaly, day }]);

    expect(marker!.label).toBe("5 anomalies");
    expect(marker!.note).toBe(
      "organization total +900.00; ana@example.com +810.00; Search +300.00; ...",
    );
  });

  it("signs a drop and runs the marker to the episode's last day", () => {
    const [marker] = anomalyMarkers([
      { ...anomaly, kind: "drop", impact: "40.00", total_impact: "120.00", end_day: "2026-08-13" },
    ]);

    expect(marker!.note).toBe("ana@example.com -120.00");
    expect(marker!.endDay).toBe("2026-08-13");
    expect(marker!.impact).toBe("120.00");
  });

  it("returns nothing without anomalies", () => {
    expect(anomalyMarkers([])).toEqual([]);
  });
});
