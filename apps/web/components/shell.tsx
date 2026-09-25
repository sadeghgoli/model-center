import Link from "next/link";
import { ReactNode } from "react";

const links = [
  ["/dashboard", "داشبورد"],
  ["/models", "مدل‌ها"],
  ["/runtimes", "ران‌تایم‌ها"],
  ["/projects", "پروژه‌ها"],
  ["/playground", "زمین بازی"],
  ["/docs", "مستندات API"],
];

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div>
      <nav className="flex flex-wrap gap-4 border-b border-stone-200 bg-white px-6 py-3">
        {links.map(([href, label]) => (
          <Link key={href} href={href}>{label}</Link>
        ))}
      </nav>
      <main className="mx-auto grid max-w-5xl gap-4 p-6">{children}</main>
    </div>
  );
}
