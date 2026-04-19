import { useState } from "react";
import { motion } from "framer-motion";
import { Check, Loader2, Lock, User, Building2, Briefcase } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { updateProfile, listWorkspaces } from "@/lib/api";
import type { Workspace } from "@/types";
import { cn } from "@/lib/utils";
import { useEffect } from "react";

const AVATAR_COLORS = [
  "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
  "#10b981", "#3b82f6", "#ef4444", "#14b8a6",
];

function initials(name: string): string {
  return name.split(" ").map(p => p[0]).join("").slice(0, 2).toUpperCase();
}

interface Field {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  icon: React.ReactNode;
  readOnly?: boolean;
}

function ProfileField({ label, value, onChange, placeholder, icon, readOnly }: Field) {
  return (
    <div>
      <label className="block text-[10px] font-bold uppercase tracking-widest text-text-secondary/40 mb-2">
        {label}
      </label>
      <div className="relative">
        <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-text-secondary/30">
          {icon}
        </span>
        <input
          type="text"
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          readOnly={readOnly}
          className={cn(
            "w-full rounded-xl border bg-surface pl-10 pr-4 py-2.5 text-sm text-text-primary placeholder:text-text-secondary/30 focus:outline-none transition-colors",
            readOnly
              ? "border-border/40 text-text-secondary/50 cursor-default select-none"
              : "border-border focus:border-accent/50"
          )}
        />
      </div>
    </div>
  );
}

export default function ProfilePage() {
  const { user, login } = useAuth();
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [jobTitle, setJobTitle] = useState(user?.job_title ?? "");
  const [department, setDepartment] = useState(user?.department ?? "");
  const [avatarColor, setAvatarColor] = useState(user?.avatar_color ?? AVATAR_COLORS[0]);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);

  useEffect(() => {
    listWorkspaces().then(setWorkspaces).catch(() => {});
  }, []);

  async function handleSave() {
    setError(null);
    if (newPassword && newPassword !== confirmPassword) {
      setError("New passwords do not match.");
      return;
    }
    setSaving(true);
    try {
      const updated = await updateProfile({
        display_name: displayName || undefined,
        job_title: jobTitle || undefined,
        department: department || undefined,
        avatar_color: avatarColor,
        current_password: currentPassword || undefined,
        new_password: newPassword || undefined,
      });
      login(updated);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  if (!user) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      transition={{ duration: 0.4 }}
      className="max-w-2xl space-y-12"
    >
      {/* Header */}
      <div>
        <p className="text-[10px] font-bold uppercase tracking-[0.18em] text-text-secondary/35 mb-3">Account</p>
        <h1 className="font-serif text-4xl lg:text-5xl font-bold tracking-tight text-text-primary">
          Your Profile
        </h1>
      </div>

      {/* Avatar + name hero */}
      <div className="flex items-center gap-6">
        <div
          className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl text-2xl font-bold text-white shadow-sm"
          style={{ backgroundColor: avatarColor }}
        >
          {initials(displayName || user.display_name)}
        </div>
        <div>
          <p className="text-xl font-semibold text-text-primary">{displayName || user.display_name}</p>
          <p className="text-sm text-text-secondary/60 mt-0.5">{user.email}</p>
          <div className="flex items-center gap-1.5 mt-2">
            <span className="rounded-full bg-accent/10 px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-accent">
              {user.org_role === "org_admin" ? "Admin" : "Member"}
            </span>
            {user.org_name && (
              <span className="text-xs text-text-secondary/40">{user.org_name}</span>
            )}
          </div>
        </div>
      </div>

      {/* Color picker */}
      <div>
        <p className="text-[10px] font-bold uppercase tracking-widest text-text-secondary/40 mb-3">Avatar Color</p>
        <div className="flex items-center gap-2.5">
          {AVATAR_COLORS.map(c => (
            <button
              key={c}
              onClick={() => setAvatarColor(c)}
              className={cn(
                "h-8 w-8 rounded-xl transition-all cursor-pointer",
                avatarColor === c ? "ring-2 ring-offset-2 ring-offset-background ring-accent scale-110" : "hover:scale-105"
              )}
              style={{ backgroundColor: c }}
            />
          ))}
        </div>
      </div>

      {/* Info fields */}
      <div className="space-y-4">
        <p className="text-[10px] font-bold uppercase tracking-widest text-text-secondary/40">Personal Info</p>
        <ProfileField
          label="Full Name"
          value={displayName}
          onChange={setDisplayName}
          placeholder="Your full name"
          icon={<User className="h-3.5 w-3.5" />}
        />
        <ProfileField
          label="Email"
          value={user.email}
          onChange={() => {}}
          icon={<User className="h-3.5 w-3.5" />}
          readOnly
        />
        <ProfileField
          label="Job Title"
          value={jobTitle}
          onChange={setJobTitle}
          placeholder="e.g. Senior Associate"
          icon={<Briefcase className="h-3.5 w-3.5" />}
        />
        <ProfileField
          label="Department"
          value={department}
          onChange={setDepartment}
          placeholder="e.g. Corporate M&A"
          icon={<Building2 className="h-3.5 w-3.5" />}
        />
      </div>

      {/* Password change */}
      <div className="space-y-4">
        <p className="text-[10px] font-bold uppercase tracking-widest text-text-secondary/40">Change Password</p>
        {(["Current password", "New password", "Confirm new password"] as const).map((label, i) => {
          const values = [currentPassword, newPassword, confirmPassword];
          const setters = [setCurrentPassword, setNewPassword, setConfirmPassword];
          return (
            <div key={label}>
              <label className="block text-[10px] font-bold uppercase tracking-widest text-text-secondary/40 mb-2">
                {label}
              </label>
              <div className="relative">
                <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-text-secondary/30" />
                <input
                  type="password"
                  value={values[i]}
                  onChange={e => setters[i](e.target.value)}
                  placeholder="••••••••"
                  className="w-full rounded-xl border border-border bg-surface pl-10 pr-4 py-2.5 text-sm text-text-primary placeholder:text-text-secondary/30 focus:outline-none focus:border-accent/50 transition-colors"
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Error */}
      {error && (
        <p className="text-sm text-risk-high bg-risk-high/8 rounded-xl px-4 py-3">{error}</p>
      )}

      {/* Save */}
      <button
        onClick={handleSave}
        disabled={saving}
        className={cn(
          "flex items-center gap-2 rounded-xl px-6 py-3 text-sm font-semibold transition-all cursor-pointer",
          saved
            ? "bg-risk-low text-white"
            : "bg-text-primary text-background hover:opacity-80"
        )}
      >
        {saving ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : saved ? (
          <><Check className="h-4 w-4" /> Saved</>
        ) : (
          "Save Changes"
        )}
      </button>

      {/* Workspaces */}
      {workspaces.length > 0 && (
        <div className="space-y-3 pt-4 border-t border-border/60">
          <p className="text-[10px] font-bold uppercase tracking-widest text-text-secondary/40">Workspaces</p>
          <div className="space-y-1.5">
            {workspaces.map(ws => (
              <div
                key={ws.workspace_id}
                className="flex items-center justify-between rounded-xl border border-border/50 bg-surface/20 px-4 py-3"
              >
                <div>
                  <p className="text-sm font-medium text-text-primary">{ws.name}</p>
                  {ws.description && (
                    <p className="text-xs text-text-secondary/40 mt-0.5">{ws.description}</p>
                  )}
                </div>
                <span className="rounded-full bg-border/50 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-text-secondary/50">
                  {ws.role === "org_admin" ? "Admin" : ws.role ?? "Member"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  );
}
