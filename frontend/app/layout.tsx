import type { Metadata } from "next";
import "./globals.css";

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
        {children}
      </body>
    </html>
  );
}

