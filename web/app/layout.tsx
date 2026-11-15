import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import ThemeKeeper from "@/components/ThemeKeeper";
import BottomNav from "@/components/shell/BottomNav";
import Footer from "@/components/shell/Footer";
import InstallPrompt from "@/components/shell/InstallPrompt";
import ServiceWorker from "@/components/shell/ServiceWorker";
import Splash from "@/components/shell/Splash";
import Tour from "@/components/shell/Tour";
import shell from "@/components/shell/shell.module.css";
import { loadMeta } from "@/lib/data";

// Geist and Geist Mono (OFL), loaded through next/font from the geist package: self-hosted,
// no font CDN. Geist has true tabular figures and the rupee sign, so prices come from one face;
// the mono is for ticker symbols only.

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
  appleWebApp: {
    capable: true,
    title: "FINN",
    statusBarStyle: "black-translucent",
    // Launch screens in FINN's canvas colour, so an installed iPhone app doesn't open on white.
    startupImage: [
      { url: "/splash/launch-1290x2796.png", media: "(device-width: 430px) and (device-height: 932px) and (-webkit-device-pixel-ratio: 3) and (orientation: portrait)" },
      { url: "/splash/launch-1179x2556.png", media: "(device-width: 393px) and (device-height: 852px) and (-webkit-device-pixel-ratio: 3) and (orientation: portrait)" },
      { url: "/splash/launch-1284x2778.png", media: "(device-width: 428px) and (device-height: 926px) and (-webkit-device-pixel-ratio: 3) and (orientation: portrait)" },
      { url: "/splash/launch-1170x2532.png", media: "(device-width: 390px) and (device-height: 844px) and (-webkit-device-pixel-ratio: 3) and (orientation: portrait)" },
      { url: "/splash/launch-1125x2436.png", media: "(device-width: 375px) and (device-height: 812px) and (-webkit-device-pixel-ratio: 3) and (orientation: portrait)" },
      { url: "/splash/launch-1242x2688.png", media: "(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 3) and (orientation: portrait)" },
      { url: "/splash/launch-828x1792.png", media: "(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 2) and (orientation: portrait)" },
      { url: "/splash/launch-750x1334.png", media: "(device-width: 375px) and (device-height: 667px) and (-webkit-device-pixel-ratio: 2) and (orientation: portrait)" },
    ],
  },
  formatDetection: { telephone: false },
  openGraph: {
    title: "FINN",
    description: "What changed in your portfolio, and why it matters.",
    type: "website",
    images: [{ url: "/icon-512.png", width: 512, height: 512, alt: "FINN" }],
  },
  twitter: { card: "summary", title: "FINN", description: "What changed in your portfolio, and why it matters." },
  other: { "mobile-web-app-capable": "yes" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#17151d",
};

// Dark is the default; a saved choice is applied before first paint to avoid a flash.
// Chrome can fire beforeinstallprompt before React hydrates: keep it for our own banner.
const installScript = `window.__finnBip=null;addEventListener("beforeinstallprompt",function(e){e.preventDefault();window.__finnBip=e;dispatchEvent(new Event("finn:bip"))});addEventListener("appinstalled",function(){try{localStorage.setItem("finn.install.v1","installed")}catch(e){}window.__finnBip=null;dispatchEvent(new Event("finn:bip"))});`;

// The launch screen shows once per visit: a second visit in the same session skips it.
const splashScript = `try{if(sessionStorage.getItem("finn.splash")){document.documentElement.dataset.splash="seen"}else{sessionStorage.setItem("finn.splash","1")}}catch(e){}`;

const themeScript = `try{var t=localStorage.getItem("finn.theme");if(t==="light"){document.documentElement.dataset.theme=t;var m=document.querySelector('meta[name="theme-color"]');m&&m.setAttribute("content","#f6f5fa")}}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const meta = loadMeta();
  return (
    <html
      lang="en-IN"
      className={`${GeistSans.variable} ${GeistMono.variable}`}
      suppressHydrationWarning
    >
      <body>
        <script dangerouslySetInnerHTML={{ __html: themeScript + splashScript + installScript }} />
        <Splash />
        <ThemeKeeper />
        <a className="skip" href="#content">
          Skip to content
        </a>
        <div className={shell.frame}>
          <main id="content" tabIndex={-1}>
            {children}
          </main>
          <Footer snapshotAt={meta.snapshot_at} pricesAsOf={meta.prices_as_of} />
        </div>
        <BottomNav />
        <InstallPrompt />
        <Tour />
        <ServiceWorker />
      </body>
    </html>
  );
}
