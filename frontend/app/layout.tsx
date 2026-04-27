import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/AppShell";
import { ActiveCallDockProvider } from "@/components/ActiveCallDockProvider";
import { ActiveSmsDockProvider } from "@/components/ActiveSmsDockProvider";
import { GlobalCallDock } from "@/components/GlobalCallDock";
import { GlobalLeftDockStack } from "@/components/GlobalLeftDockStack";

export const metadata: Metadata = {
  title: "AI Voicebot Control Center",
  description: "Real-time monitoring and management for AI Voice Assistant",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body className="antialiased">
        <ActiveCallDockProvider>
          <ActiveSmsDockProvider>
            <AppShell>{children}</AppShell>
            <GlobalCallDock />
            <GlobalLeftDockStack />
          </ActiveSmsDockProvider>
        </ActiveCallDockProvider>
      </body>
    </html>
  );
}

