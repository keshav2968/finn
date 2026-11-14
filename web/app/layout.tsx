import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Two free fonts (OFL), self-hosted from @fontsource-variable so builds need no font CDN.
// Plus Jakarta Sans: headings, names and copy (its latin-ext file carries ₹).
// JetBrains Mono: tickers, ₹ prices and percentages only (tabular by design; it has no
// ₹ glyph, so the sign falls through to Jakarta's latin-ext file).
const jakarta = localFont({
  src: "../node_modules/@fontsource-variable/plus-jakarta-sans/files/plus-jakarta-sans-latin-wght-normal.woff2",
  weight: "200 800",
  variable: "--font-jakarta",
  display: "swap",
  adjustFontFallback: false, // no metric fallback in between, so ₹ reaches the latin-ext file
});

const jakartaExt = localFont({
  src: "../node_modules/@fontsource-variable/plus-jakarta-sans/files/plus-jakarta-sans-latin-ext-wght-normal.woff2",
  weight: "200 800",
  variable: "--font-jakarta-ext",
  display: "swap",
});

const jbm = localFont({
  src: "../node_modules/@fontsource-variable/jetbrains-mono/files/jetbrains-mono-latin-wght-normal.woff2",
  weight: "100 800",
  variable: "--font-jbm",
  display: "swap",
  adjustFontFallback: false,
});

export const metadata: Metadata = {
  title: "Finn",
  description: "What changed in your portfolio, and why it matters.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg", apple: "/icon-180.png" },
  appleWebApp: { capable: true, title: "Finn", statusBarStyle: "black-translucent" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0b0e14",
};

// Dark is the default; a saved choice is applied before first paint to avoid a flash.
const themeScript = `try{var t=localStorage.getItem("finn.theme");if(t==="light"){document.documentElement.dataset.theme=t;var m=document.querySelector('meta[name="theme-color"]');m&&m.setAttribute("content","#f5f3ee")}}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en-IN"
      data-theme="dark"
      className={`${jakarta.variable} ${jakartaExt.variable} ${jbm.variable}`}
      suppressHydrationWarning
    >
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        {children}
      </body>
    </html>
  );
}
