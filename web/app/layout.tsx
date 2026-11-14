import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// IBM Plex Sans (OFL), self-hosted from @fontsource-variable so builds need no font CDN.
// Its digits are tabular by default; the latin-ext subset carries the ₹ sign.
const plex = localFont({
  src: "../node_modules/@fontsource-variable/ibm-plex-sans/files/ibm-plex-sans-latin-wght-normal.woff2",
  weight: "100 700",
  variable: "--font-plex",
  display: "swap",
});

const plexExt = localFont({
  src: "../node_modules/@fontsource-variable/ibm-plex-sans/files/ibm-plex-sans-latin-ext-wght-normal.woff2",
  weight: "100 700",
  variable: "--font-plex-ext",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: "FINN",
  description: "What changed in your portfolio, and why it matters.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon.svg", apple: "/icon-180.png" },
  appleWebApp: { capable: true, title: "FINN", statusBarStyle: "default" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f6f1e6" },
    { media: "(prefers-color-scheme: dark)", color: "#111316" },
  ],
};

// Light is the default; a saved choice is applied before first paint to avoid a flash.
const themeScript = `try{var t=localStorage.getItem("finn.theme");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN" data-theme="light" className={`${plex.variable} ${plexExt.variable}`} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
