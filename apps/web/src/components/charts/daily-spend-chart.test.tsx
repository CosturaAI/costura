import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BucketedSpendChart, SpendTooltip } from "./daily-spend-chart";
import { buildRows } from "./spend-rows";

const data = {
  buckets: ["2026-09-15", "2026-09-16"],
  series: [
    {
      key: "model-a",
      label: "Model A",
      provider: "openai",
      values: [10, 15],
      total: 25,
    },
  ],
  other: null,
  total: [10, 15],
};

describe("BucketedSpendChart", () => {
  it("draws a dashed continuation from the last actual bucket", () => {
    render(
      <BucketedSpendChart
        data={data}
        interval="day"
        allowCumulative={false}
        future={{
          mode: "linear",
          lookback: 8,
          horizon: 2,
          buckets: ["2026-09-17", "2026-09-18"],
          anchor: 15,
          values: [18, 21],
        }}
      />,
    );

    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent("projected");
    expect(screen.getByRole("table")).toHaveTextContent("21.00");
    expect(
      buildRows(
        {
          month: "",
          dimension: "model",
          source: "cost",
          days: ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"],
          series: [
            {
              key: "model-a",
              label: "Model A",
              provider: "openai",
              values: ["10", "15", "0", "0"],
              total: "25",
            },
          ],
          other: null,
          total: ["10", "15", "0", "0"],
          month_total: "25",
        },
        "daily",
        null,
        [],
        {
          mode: "linear",
          lookback: 8,
          horizon: 2,
          buckets: ["2026-09-17", "2026-09-18"],
          anchor: 15,
          values: [18, 21],
        },
      ).map((row) => row.__projection__),
    ).toEqual([undefined, 15, 18, 21]);
  });

  it("summarizes each dimension on the x-axis", () => {
    render(
      <BucketedSpendChart data={data} interval="day" axis="dimension" valueLabel="Daily average" />,
    );

    expect(screen.getByRole("table", { name: /Daily average by dimension/ })).toHaveTextContent(
      "Model A",
    );
    expect(screen.getByRole("table", { name: /Daily average by dimension/ })).toHaveTextContent(
      "25.00",
    );
  });

  it("draws anomaly markers as one dot per first bucket with a summary line", () => {
    const markers = [
      {
        day: "2026-09-15",
        endDay: "2026-09-16",
        kind: "open",
        label: "2 anomalies",
        note: "organization total +15.00; Model A +8.00",
        impact: "15.00",
        count: 2,
        emphasis: "primary" as const,
        href: "/anomalies/7",
      },
    ];
    render(
      <BucketedSpendChart
        data={data}
        interval="day"
        allowCumulative={false}
        markers={markers}
        legend="markers"
      />,
    );

    const legend = screen.getByRole("list", { name: "Legend" });
    expect(legend).not.toHaveTextContent("Model A");
    expect(legend).toHaveTextContent("anomaly");
    expect(screen.getByRole("list", { name: "Chart markers" })).toHaveTextContent(
      "2 open anomalies on 1 day; worst Sep 15, organization total +15.00 USD",
    );
    expect(screen.getByRole("link", { name: "All anomalies" })).toHaveAttribute(
      "href",
      "/anomalies",
    );
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows[1]).toHaveTextContent("anomaly: 2 anomalies");
    expect(rows[2]).not.toHaveTextContent("anomaly: 2 anomalies");
  });

  it("draws no marker legend or summary without anomalies", () => {
    render(<BucketedSpendChart data={data} interval="day" allowCumulative={false} />);

    expect(screen.getByRole("list", { name: "Legend" })).not.toHaveTextContent("anomaly");
    expect(screen.queryByRole("list", { name: "Chart markers" })).not.toBeInTheDocument();
  });
});

describe("BucketedSpendChart on the dimension axis", () => {
  it("lists each series total in the table beside the bars", () => {
    render(
      <BucketedSpendChart
        data={{
          ...data,
          series: [
            {
              key: "k1",
              label: "prod-agent (apikey_01)",
              provider: "anthropic",
              values: [4, 6],
              total: 10,
            },
            { key: "k2", label: "batch", provider: "anthropic", values: [1, 2], total: 3 },
          ],
          total: [5, 8],
        }}
        interval="day"
        axis="dimension"
        valueLabel="Total across shown buckets"
      />,
    );
    expect(screen.getAllByText("Total across shown buckets").length).toBeGreaterThan(0);
    expect(screen.getByRole("table")).toHaveTextContent("10.00");
  });
});

describe("SpendTooltip", () => {
  const keys = [{ key: "model-a", label: "Model A", color: "red" }];

  it("renders nothing while inactive or without a row", () => {
    const { container } = render(
      <SpendTooltip active={false} keys={keys} currency="USD" mode="daily" showShare={false} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("names the day, the total, the projection band and the anomalies of the day", () => {
    render(
      <SpendTooltip
        active
        payload={[
          {
            payload: {
              day: "2026-09-16",
              total: 15,
              "model-a": 15,
              __projection__: 18,
              __projection_low__: 16,
              __projection_high__: 20,
              __markers__: [{ day: "2026-09-16", label: "spike on Model A", impact: "5" }],
            },
          },
        ]}
        keys={keys}
        currency="USD"
        mode="cumulative"
        showShare
      />,
    );
    expect(screen.getByText("Sep 16")).toBeInTheDocument();
    expect(screen.getByText(/to date/)).toBeInTheDocument();
    expect(screen.getByText(/projected 18\.00 USD \(16\.00 to 20\.00\)/)).toBeInTheDocument();
    expect(screen.getByText(/spike on Model A/)).toBeInTheDocument();
  });
});
