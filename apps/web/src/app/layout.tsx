import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import type { Metadata } from "next";
import localFont from "next/font/local";
import { cookies, headers } from "next/headers";
import Script from "next/script";

import { brandName, themeAttribute, themeName } from "@/lib/theme";
import { ViewportProvider } from "@/lib/viewport";
import { VIEWPORT_COOKIE, parseViewportWidth } from "@/lib/viewport-cookie";

import "./globals.css";

const inter = localFont({
  src: "../fonts/InterVariable.woff2",
  variable: "--font-inter",
  weight: "100 900",
  display: "swap",
});

const jetbrainsMono = localFont({
  src: "../fonts/JetBrainsMono-Regular.woff2",
  variable: "--font-jetbrains-mono",
  weight: "400",
  display: "swap",
});

export async function generateMetadata(): Promise<Metadata> {
  return {
    title: { default: brandName(), template: `%s · ${brandName()}` },
    description:
      "Know who spent what on AI, across every provider, with numbers that tie out to each provider's own report.",
    icons: {
      icon: [
        { url: "/favicon.ico", sizes: "16x16 32x32 48x48" },
        { url: "/brand/favicon.svg", type: "image/svg+xml" },
      ],
      apple: { url: "/apple-touch-icon.png", type: "image/png" },
    },
  };
}

const themeCssByName = new Map<string, string | null>();

/** A host theme other than `costura` overrides the imported default. Read from disk once per
 * theme name: the files ship with the build and do not change while the server runs. */
function hostThemeCss(): string | null {
  const name = themeName();
  if (name === "costura") return null;
  if (!themeCssByName.has(name)) themeCssByName.set(name, readThemeCss(name));
  return themeCssByName.get(name) ?? null;
}

function readThemeCss(name: string): string | null {
  const dir = path.join(process.cwd(), "src/themes");
  const parts: string[] = [];
  for (const file of [`${name}.css`, `${name}-dark.css`]) {
    const full = path.join(dir, file);
    if (existsSync(full)) parts.push(readFileSync(full, "utf8"));
  }
  return parts.length > 0 ? parts.join("\n") : null;
}

export default async function RootLayout({ children }: LayoutProps<"/">) {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  const width = parseViewportWidth((await cookies()).get(VIEWPORT_COOKIE)?.value);
  const extra = hostThemeCss();
  return (
    <html
      lang="en"
      data-theme={themeAttribute()}
      className={`${inter.variable} ${jetbrainsMono.variable} h-full`}
    >
      <body className="flex min-h-dvh flex-col">
        <Script id="sidebar-collapsed" strategy="beforeInteractive" nonce={nonce}>
          {`try{if(localStorage.getItem("costura.sidebar.collapsed")==="1")document.documentElement.dataset.sidebar="collapsed"}catch(e){}`}
        </Script>
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:text-foreground"
        >
          Skip to content
        </a>
        {extra ? <style>{extra}</style> : null}
        <ViewportProvider width={width}>{children}</ViewportProvider>
      </body>
    </html>
  );
}
