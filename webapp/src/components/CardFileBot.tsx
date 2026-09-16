import {
  ArrowLeft,
  BadgeHelp,
  Check,
  CircleUserRound,
  CopyMinus,
  DatabaseZap,
  FileCheck2,
  FileKey2,
  FileSearch,
  Files,
  History,
  LogOut,
  Minus,
  Moon,
  Plus,
  Play,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
  UserPlus,
  WandSparkles,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

type Screen = "home" | "scrape" | "accounts" | "history" | "settings" | "help";
type Theme = "dark" | "light";
type Surface = "glossy" | "solid";
type Action = { id: string; label: string; icon: LucideIcon; tone: string };

type TelegramWebApp = {
  ready?: () => void;
  expand?: () => void;
  sendData?: (data: string) => void;
  colorScheme?: "light" | "dark";
  HapticFeedback?: {
    impactOccurred?: (style: "light" | "medium" | "heavy") => void;
    selectionChanged?: () => void;
    notificationOccurred?: (type: "success" | "error" | "warning") => void;
  };
};

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

const fileActions: Action[] = [
  { id: "clean", label: "Clean", icon: WandSparkles, tone: "violet" },
  { id: "live", label: "Live Check", icon: ShieldCheck, tone: "mint" },
  { id: "filter", label: "Keywords", icon: FileKey2, tone: "peach" },
  { id: "findbin", label: "Find BIN", icon: FileSearch, tone: "butter" },
  { id: "split", label: "Split", icon: CopyMinus, tone: "sky" },
  { id: "dedup", label: "Delete duplicates", icon: Files, tone: "rose" },
];

const dataActions: (Action & { screen: Screen })[] = [
  { id: "scrape", label: "Scrape a source", icon: DatabaseZap, tone: "violet", screen: "scrape" },
  { id: "accounts", label: "My accounts", icon: CircleUserRound, tone: "mint", screen: "accounts" },
  { id: "history", label: "History", icon: History, tone: "butter", screen: "history" },
];

const historyItems = [
  { title: "Clean · cards_0916.txt", time: "Just now", status: "Complete", matched: "2,418", valid: "2,306", tone: "mint" },
  { title: "Live Check · September", time: "18 min ago", status: "Running", matched: "864", valid: "719", tone: "violet" },
  { title: "Keyword scan · archive", time: "Yesterday, 21:42", status: "Complete", matched: "438", valid: "412", tone: "peach" },
  { title: "Split · export.csv", time: "Sep 14, 08:16", status: "Failed", matched: "1,204", valid: "—", tone: "rose" },
];

function telegram() {
  return typeof window === "undefined" ? undefined : window.Telegram?.WebApp;
}

function sendTelegram(action: string, detail?: Record<string, unknown>) {
  telegram()?.sendData?.(JSON.stringify({ action, ...detail }));
}

function haptic(kind: "selection" | "success" | "light" = "light") {
  const feedback = telegram()?.HapticFeedback;
  if (kind === "selection") feedback?.selectionChanged?.();
  else if (kind === "success") feedback?.notificationOccurred?.("success");
  else feedback?.impactOccurred?.("light");
}

export function CardFileBot() {
  const [screen, setScreen] = useState<Screen>("home");
  const [selected, setSelected] = useState<Action | null>(null);
  const [theme, setTheme] = useState<Theme>("dark");
  const [surface, setSurface] = useState<Surface>("glossy");
  const [toast, setToast] = useState("");
  const [running, setRunning] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const app = telegram();
    app?.ready?.();
    app?.expand?.();
    if (app?.colorScheme === "light") setTheme("light");
  }, []);

  useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  const notify = (message: string) => {
    setToast(message);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 2400);
  };

  const open = (next: Screen) => {
    haptic("light");
    setScreen(next);
  };

  const runSelected = () => {
    if (!selected || running) return;
    setRunning(true);
    haptic("light");
    sendTelegram(selected.id);
    setTimeout(() => {
      setRunning(false);
      haptic("success");
      notify(`${selected.label} request sent`);
    }, 1050);
  };

  return (
    <div className={`app-theme ${theme} ${surface}`}>
      <div className="app-shell">
        {screen === "home" ? (
          <Home
            selected={selected}
            onSelect={(action) => { setSelected(action); haptic("selection"); }}
            open={open}
            theme={theme}
            setTheme={setTheme}
          />
        ) : (
          <div className="screen-enter">
            <SubHeader title={screen === "scrape" ? "Scrape source" : screen.charAt(0).toUpperCase() + screen.slice(1)} onBack={() => setScreen("home")} />
            {screen === "scrape" && <ScrapeScreen notify={notify} />}
            {screen === "accounts" && <AccountsScreen notify={notify} />}
            {screen === "history" && <HistoryScreen />}
            {screen === "settings" && <SettingsScreen theme={theme} setTheme={setTheme} surface={surface} setSurface={setSurface} notify={notify} />}
            {screen === "help" && <HelpScreen />}
          </div>
        )}

        {screen === "home" && (
          <BottomRun selected={selected} running={running} onRun={runSelected} />
        )}
        {toast && <Toast message={toast} />}
      </div>
    </div>
  );
}

function Home({ selected, onSelect, open, theme, setTheme }: { selected: Action | null; onSelect: (action: Action) => void; open: (screen: Screen) => void; theme: Theme; setTheme: (theme: Theme) => void }) {
  return (
    <>
      <header className="main-header">
        <div className="brand-mark"><FileCheck2 size={21} strokeWidth={2.4} /></div>
        <div className="brand-copy">
          <span>Card File Bot</span>
          <strong>File desk</strong>
        </div>
        <div className="header-actions">
          <button className="icon-button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button>
          <div className="status-pill"><i />Connected</div>
        </div>
      </header>

      <main className="main-content">
        <div className="welcome-row">
          <div><span className="eyebrow">Workspace</span><h1>What are we running?</h1></div>
          <span className="job-count">03 active</span>
        </div>
        <SectionLabel label="Files" meta="Choose one" />
        <div className="action-grid">
          {fileActions.map((action) => <ActionTile key={action.id} action={action} active={selected?.id === action.id} onClick={() => onSelect(action)} />)}
        </div>

        <SectionLabel label="Data" />
        <div className="action-grid data-grid">
          {dataActions.map((action) => <ActionTile key={action.id} action={action} active={false} onClick={() => open(action.screen)} />)}
        </div>

        <SectionLabel label="More" />
        <div className="compact-grid">
          <button className="compact-action panel" onClick={() => open("settings")}><span className="icon-clay tone-sky"><Settings size={18} /></span><span>Settings</span></button>
          <button className="compact-action panel" onClick={() => open("help")}><span className="icon-clay tone-peach"><BadgeHelp size={18} /></span><span>Help</span></button>
        </div>
        <footer>@Lord_Jat · Secure Telegram utility</footer>
      </main>
    </>
  );
}

function SectionLabel({ label, meta }: { label: string; meta?: string }) {
  return <div className="section-label"><span>{label}</span>{meta && <small>{meta}</small>}</div>;
}

function ActionTile({ action, active, onClick }: { action: Action; active: boolean; onClick: () => void }) {
  const Icon = action.icon;
  return (
    <button className={`action-tile panel ${active ? "selected" : ""}`} onClick={onClick} aria-pressed={active}>
      <span className={`icon-clay tone-${action.tone}`}><Icon size={22} strokeWidth={2.15} /></span>
      <span>{action.label}</span>
      {active && <span className="selected-check"><Check size={12} strokeWidth={3} /></span>}
    </button>
  );
}

function SubHeader({ title, onBack }: { title: string; onBack: () => void }) {
  return <header className="sub-header"><button className="icon-button" onClick={onBack} aria-label="Back"><ArrowLeft size={20} /></button><div><span>Card File Bot</span><h1>{title}</h1></div><div className="status-dot" aria-label="Connected" /></header>;
}

function ScrapeScreen({ notify }: { notify: (message: string) => void }) {
  const [sources, setSources] = useState(["Web"]);
  const [range, setRange] = useState("30d");
  const [mode, setMode] = useState("contains");
  const [format, setFormat] = useState("CSV");
  const [limit, setLimit] = useState(500);
  const [dryRun, setDryRun] = useState(true);
  const [keyword, setKeyword] = useState("");
  const [progress, setProgress] = useState(0);

  const toggleSource = (value: string) => {
    haptic("selection");
    setSources((current) => current.includes(value) ? current.filter((item) => item !== value) : [...current, value]);
  };

  const run = () => {
    if (progress > 0 && progress < 100) return;
    setProgress(8);
    sendTelegram("scrape", { sources, keyword, range, matchMode: mode, limit, format: format.toLowerCase(), dryRun });
    const timer = setInterval(() => {
      setProgress((value) => {
        const next = Math.min(100, value + 12);
        if (next === 100) { clearInterval(timer); haptic("success"); notify("Scrape configuration sent"); }
        return next;
      });
    }, 150);
  };

  return <main className="sub-content with-action">
    <div className="intro"><span className="eyebrow">Configure job</span><p>Build a focused source scan in a few taps.</p></div>
    <FormCard title="Sources" hint={`${sources.length} selected`}>
      <div className="chips">{["Web", "Telegram", "Paste", "File"].map((item) => <button key={item} className={sources.includes(item) ? "chip active" : "chip"} onClick={() => toggleSource(item)}>{sources.includes(item) && <Check size={13} />}{item}</button>)}</div>
    </FormCard>
    <FormCard title="Keyword"><label className="input-wrap"><Search size={17} /><input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="Enter keyword or pattern" /></label></FormCard>
    <FormCard title="Date range"><Pills values={["All", "7d", "30d", "90d", "Month", "Custom"]} value={range} onChange={setRange} /></FormCard>
    <FormCard title="Match mode"><Pills values={["contains", "word", "exact", "regex", "field"]} value={mode} onChange={setMode} compact /></FormCard>
    <FormCard title="Result limit">
      <div className="stepper"><button onClick={() => setLimit(Math.max(50, limit - 50))} aria-label="Decrease limit"><Minus size={18} /></button><strong>{limit.toLocaleString()}</strong><button onClick={() => setLimit(Math.min(5000, limit + 50))} aria-label="Increase limit"><Plus size={18} /></button></div>
    </FormCard>
    <FormCard title="Output"><Pills values={["TXT", "CSV", "JSON"]} value={format} onChange={setFormat} /><label className="switch-row"><span><strong>Dry run</strong><small>Preview without saving results</small></span><button className={`switch ${dryRun ? "on" : ""}`} onClick={() => setDryRun(!dryRun)} role="switch" aria-checked={dryRun}><i /></button></label></FormCard>
    <div className="sticky-run"><button className="primary-run" onClick={run}><Play size={17} fill="currentColor" />{progress > 0 && progress < 100 ? `Running · ${progress}%` : "Run scrape"}</button>{progress > 0 && <div className="run-progress"><i style={{ width: `${progress}%` }} /></div>}</div>
  </main>;
}

function FormCard({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return <section className="form-card panel"><div className="form-title"><h2>{title}</h2>{hint && <span>{hint}</span>}</div>{children}</section>;
}

function Pills({ values, value, onChange, compact = false }: { values: string[]; value: string; onChange: (value: string) => void; compact?: boolean }) {
  return <div className={`pills ${compact ? "compact" : ""}`}>{values.map((item) => <button key={item} className={value === item ? "active" : ""} onClick={() => { onChange(item); haptic("selection"); }}>{item}</button>)}</div>;
}

function AccountsScreen({ notify }: { notify: (message: string) => void }) {
  const [accounts, setAccounts] = useState([
    { id: 1, name: "@lord_workspace", detail: "Primary · active now", online: true },
    { id: 2, name: "@archive_node", detail: "Synced 24 min ago", online: true },
    { id: 3, name: "@research_feed", detail: "Reconnect required", online: false },
  ]);
  const add = () => { const next = accounts.length + 1; setAccounts([...accounts, { id: Date.now(), name: `@new_account_${next}`, detail: "Added just now", online: true }]); sendTelegram("add_account"); notify("Demo account added"); };
  const logout = (id: number) => { setAccounts((items) => items.map((item) => item.id === id ? { ...item, online: false, detail: "Logged out" } : item)); sendTelegram("logout", { accountId: id }); notify("Account logged out"); };
  return <main className="sub-content"><div className="intro"><span className="eyebrow">Connections</span><p>Manage the sources attached to this bot.</p></div><div className="account-list panel">{accounts.map((account) => <div className="account-row" key={account.id}><div className="avatar">{account.name.slice(1, 3).toUpperCase()}<i className={account.online ? "online" : ""} /></div><div className="account-copy"><strong>{account.name}</strong><span>{account.detail}</span></div>{account.online && <button className="logout-button" onClick={() => logout(account.id)} aria-label={`Log out ${account.name}`}><LogOut size={17} /></button>}</div>)}</div><button className="secondary-action" onClick={add}><UserPlus size={18} />Add account</button></main>;
}

function HistoryScreen() {
  const [loading, setLoading] = useState(true);
  useEffect(() => { const timer = setTimeout(() => setLoading(false), 700); return () => clearTimeout(timer); }, []);
  return <main className="sub-content"><div className="intro"><span className="eyebrow">Activity</span><p>Your latest processing runs and results.</p></div>{loading ? <div className="skeleton-list">{[1, 2, 3].map((item) => <div className="skeleton-card" key={item}><i /><span /><span /></div>)}</div> : <div className="timeline">{historyItems.map((item) => <article className="timeline-item panel" key={item.title}><i className={`timeline-dot tone-${item.tone}`} /><div className="timeline-top"><div><strong>{item.title}</strong><span>{item.time}</span></div><em className={`status-${item.tone}`}>{item.status}</em></div><div className="metrics"><span><small>Matched</small><strong>{item.matched}</strong></span><span><small>Valid</small><strong>{item.valid}</strong></span></div></article>)}</div>}</main>;
}

function SettingsScreen({ theme, setTheme, surface, setSurface, notify }: { theme: Theme; setTheme: (value: Theme) => void; surface: Surface; setSurface: (value: Surface) => void; notify: (message: string) => void }) {
  const [haptics, setHaptics] = useState(true);
  const setAndNotify = <T extends string>(setter: (value: T) => void, value: T, label: string) => { setter(value); haptic("selection"); notify(label); };
  return <main className="sub-content"><div className="intro"><span className="eyebrow">Appearance</span><p>Make the workspace feel exactly right.</p></div><FormCard title="Theme"><Pills values={["Dark", "Light"]} value={theme.charAt(0).toUpperCase() + theme.slice(1)} onChange={(value) => setAndNotify(setTheme, value.toLowerCase() as Theme, `${value} mode enabled`)} /></FormCard><FormCard title="Surface style"><Pills values={["Glossy", "Solid"]} value={surface.charAt(0).toUpperCase() + surface.slice(1)} onChange={(value) => setAndNotify(setSurface, value.toLowerCase() as Surface, `${value} surfaces enabled`)} /></FormCard><section className="form-card panel"><label className="switch-row"><span><strong>Haptic feedback</strong><small>Feel selections and confirmations</small></span><button className={`switch ${haptics ? "on" : ""}`} onClick={() => setHaptics(!haptics)} role="switch" aria-checked={haptics}><i /></button></label></section><div className="theme-preview panel"><Sparkles size={20} /><div><strong>{theme === "dark" ? "Night workspace" : "Pearl workspace"}</strong><span>{surface === "glossy" ? "Reflective glass layers" : "Calm opaque panels"}</span></div></div></main>;
}

function HelpScreen() {
  return <main className="sub-content"><div className="help-mark"><BadgeHelp size={34} /></div><div className="intro centered"><span className="eyebrow">Quick guide</span><p>Select a file tool, tap Run, and your request is sent securely to the Telegram bot.</p></div><div className="help-list panel"><div><span>01</span><p><strong>Choose a tool</strong><small>Pick one action from the home grid.</small></p></div><div><span>02</span><p><strong>Review and run</strong><small>The bottom bar always shows your selection.</small></p></div><div><span>03</span><p><strong>Track the result</strong><small>Open History to see matched and valid counts.</small></p></div></div><div className="support-note">Built for <strong>@Lord_Jat</strong></div></main>;
}

function BottomRun({ selected, running, onRun }: { selected: Action | null; running: boolean; onRun: () => void }) {
  return <div className="bottom-bar"><div className="run-copy"><span>{selected ? "Ready to run" : "Select a file action"}</span><strong>{selected?.label ?? "Nothing selected"}</strong></div><button className="run-button" disabled={!selected || running} onClick={onRun}>{running ? <span className="spinner" /> : <Play size={17} fill="currentColor" />}Run</button></div>;
}

function Toast({ message }: { message: string }) {
  return <div className="toast"><span><Check size={14} strokeWidth={3} /></span>{message}</div>;
}