import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Two free fonts (OFL), self-hosted from @fontsource-variable so builds need no font CDN.
// Instrument Sans: text and titles (tabular digits on). Geist Mono: every figure and
// ticker; its latin-ext file carries the ₹ sign.
const instrument = localFont({
  src: "../node_modules/@fontsource-variable/instrument-sans/files/instrument-sans-latin-wght-normal.woff2",
  weight: "400 700",
  variable: "--font-instrument",
  display: "swap",
});

const geistMono = localFont({
  src: "../node_modules/@fontsource-variable/geist-mono/files/geist-mono-latin-wght-normal.woff2",
  weight: "100 900",
  variable: "--font-geist-mono",
  display: "swap",
  adjustFontFallback: false, // no metric fallback in between, so ₹ reaches the latin-ext file
});

const geistMonoExt = localFont({
  src: "../node_modules/@fontsource-variable/geist-mono/files/geist-mono-latin-ext-wght-normal.woff2",
  weight: "100 900",
  variable: "--font-geist-mono-ext",
  display: "swap",
  preload: false,
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
  themeColor: "#0e1013",
};

// Dark is the default; a saved choice is applied before first paint to avoid a flash.
const themeScript = `try{var t=localStorage.getItem("finn.theme");if(t==="light"){document.documentElement.dataset.theme=t;var m=document.querySelector('meta[name="theme-color"]');m&&m.setAttribute("content","#f6f1e6")}}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html
      lang="en-IN"
      data-theme="dark"
      className={`${instrument.variable} ${geistMono.variable} ${geistMonoExt.variable}`}
      suppressHydrationWarning
    >
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
        {children}
      </body>
    </html>
  );
}
