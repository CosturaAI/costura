import { afterEach, describe, expect, it } from "vitest";

import { brandName, colorScheme, themeAttribute, themeName } from "./theme";

describe("theme selection", () => {
  afterEach(() => {
    delete process.env.COSTURA_BRAND_NAME;
    delete process.env.COSTURA_COLOR_SCHEME;
    delete process.env.COSTURA_THEME;
  });

  it("defaults to the Costura light theme", () => {
    expect(brandName()).toBe("Costura");
    expect(colorScheme()).toBe("light");
    expect(themeAttribute()).toBeUndefined();
    expect(themeName()).toBe("costura");
  });

  it("reads the host theme, scheme and brand", () => {
    process.env.COSTURA_BRAND_NAME = " Northwind ";
    process.env.COSTURA_COLOR_SCHEME = "dark";
    process.env.COSTURA_THEME = "northwind";
    expect(brandName()).toBe("Northwind");
    expect(colorScheme()).toBe("dark");
    expect(themeAttribute()).toBe("dark");
    expect(themeName()).toBe("northwind");
  });

  it("keeps system as its own attribute and rejects a path in the theme name", () => {
    process.env.COSTURA_COLOR_SCHEME = "system";
    process.env.COSTURA_THEME = "../secrets/costura";
    expect(themeAttribute()).toBe("system");
    expect(themeName()).toBe("secretscostura");
  });
});
