import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";
import ThemeKeeper from "@/components/ThemeKeeper";
import BottomNav from "@/components/shell/BottomNav";
import Footer from "@/components/shell/Footer";
import InstallPrompt from "@/components/shell/InstallPrompt";
import ServiceWorker from "@/components/shell/ServiceWorker";
import shell from "@/components/shell/shell.module.css";
import { loadMeta } from "@/lib/data";

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
  title: "FINN",
  description: "What changed in your portfolio, and why it matters.",
  applicationName: "FINN",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }, { url: "/icon-192.png", sizes: "192x192", type: "image/png" }],
    apple: [{ url: "/icon-180.png", sizes: "180x180" }],
  },
  // iOS home-screen app: standalone, with the status bar drawn over FINN's own dark canvas.
  appleWebApp: { capable: true, title: "FINN", statusBarStyle: "black-translucent" },
  formatDetection: { telephone: false },
  other: { "mobile-web-app-capable": "yes" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0b0e14",
};

// Dark is the default; a saved choice is applied before first paint to avoid a flash.
// Chrome can fire beforeinstallprompt before React hydrates: keep it for our own banner.
const installScript = `window.__finnBip=null;addEventListener("beforeinstallprompt",function(e){e.preventDefault();window.__finnBip=e;dispatchEvent(new Event("finn:bip"))});addEventListener("appinstalled",function(){try{localStorage.setItem("finn.install.v1","installed")}catch(e){}window.__finnBip=null;dispatchEvent(new Event("finn:bip"))});`;

const themeScript = `try{var t=localStorage.getItem("finn.theme");if(t==="light"){document.documentElement.dataset.theme=t;var m=document.querySelector('meta[name="theme-color"]');m&&m.setAttribute("content","#f5f3ee")}}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const meta = loadMeta();
  return (
    <html
      lang="en-IN"
      className={`${jakarta.variable} ${jakartaExt.variable} ${jbm.variable}`}
      suppressHydrationWarning
    >
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeScript + installScript }} />
        <ThemeKeeper />
        <div className={shell.frame}>
          {children}
          <Footer snapshotAt={meta.snapshot_at} pricesAsOf={meta.prices_as_of} />
        </div>
        <BottomNav />
        <InstallPrompt />
        <ServiceWorker />
      </body>
    </html>
  );
}
