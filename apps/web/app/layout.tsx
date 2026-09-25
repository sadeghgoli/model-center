import "./globals.css";
import { ReactNode } from "react";
import { Providers } from "./providers";

export const metadata = { title: "مرکز مدل" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fa" dir="rtl">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
