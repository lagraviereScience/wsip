import {
  Flame,
  Gamepad2,
  LayoutDashboard,
  Library,
  Settings,
  ShoppingBag,
  UserRound,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: `/${string}`;
  label: string;
  shortLabel: string;
  icon: LucideIcon;
}

/** Primary navigation, in the order required by spec §30. */
export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", shortLabel: "Home", icon: LayoutDashboard },
  { href: "/profile", label: "My Gamer Profile", shortLabel: "Profile", icon: UserRound },
  { href: "/library", label: "My Game Library", shortLabel: "Library", icon: Library },
  { href: "/play", label: "Games I Should Play", shortLabel: "Play", icon: Gamepad2 },
  { href: "/buy", label: "Games I Should Buy", shortLabel: "Buy", icon: ShoppingBag },
  { href: "/trending", label: "Trending Games", shortLabel: "Trending", icon: Flame },
  { href: "/settings", label: "Settings", shortLabel: "Settings", icon: Settings },
];
