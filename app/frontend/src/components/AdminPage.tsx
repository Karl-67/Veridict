import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import { Plus, Trash2, UserPlus, Copy, Check, Shield, Users, Briefcase, Loader2, ChevronRight, Unlock, FileText } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { cn } from "@/lib/utils";
import RagDocumentPanel from "./RagDocumentPanel";

const API_BASE = "http://localhost:8000/api";

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem("veridict_token");
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return headers;
}

async function api(method: string, path: string, body?: unknown) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: authHeaders(),
    credentials: "include",
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  return res.json();
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface OrgUser { user_id: string; email: string; display_name: string; job_title: string | null; department: string | null; avatar_color: string; org_role: string; locked: boolean; created_at: string; }
interface Workspace { workspace_id: string; name: string; description: string | null; member_count: number; created_at: string; }
interface WorkspaceMember { user_id: string; email: string; display_name: string; job_title: string | null; department: string | null; avatar_color: string; role: string; }
interface Invite { invite_id: string; email: string; org_role: string; workspace_name: string | null; workspace_role: string; invited_by: string; expires_at: string; created_at: string; }

// ── Avatar ────────────────────────────────────────────────────────────────────

function Avatar({ name, color, size = "sm" }: { name: string; color: string; size?: "sm" | "md" }) {
  const initials = name.split(" ").map(p => p[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div
      className={cn("rounded-full flex items-center justify-center font-bold text-white shrink-0", size === "sm" ? "h-7 w-7 text-[10px]" : "h-9 w-9 text-xs")}
      style={{ backgroundColor: color }}
    >
      {initials}
    </div>
  );
}

// ── Role badge ────────────────────────────────────────────────────────────────

const ROLE_COLORS: Record<string, string> = {
  org_admin: "bg-accent/15 text-accent border-accent/30",
  member: "bg-border/40 text-text-secondary border-border",
  workspace_admin: "bg-risk-medium/15 text-risk-medium border-risk-medium/30",
  reviewer: "bg-risk-low/15 text-risk-low border-risk-low/30",
  viewer: "bg-border/40 text-text-secondary border-border",
};

function RoleBadge({ role }: { role: string }) {
  return (
    <span className={cn("text-[10px] font-bold px-1.5 py-0.5 rounded border uppercase tracking-wide", ROLE_COLORS[role] ?? ROLE_COLORS.member)}>
      {role.replace("_", " ")}
    </span>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

type Tab = "users" | "workspaces" | "invites" | "rag";

export default function AdminPage({ onBack }: { onBack: () => void }) {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>("users");
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedWorkspace, setSelectedWorkspace] = useState<Workspace | null>(null);
  const [wsMembers, setWsMembers] = useState<WorkspaceMember[]>([]);

  // Invite form
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteOrgRole, setInviteOrgRole] = useState("member");
  const [inviteWsId, setInviteWsId] = useState("");
  const [inviteWsRole, setInviteWsRole] = useState("reviewer");
  const [inviteLoading, setInviteLoading] = useState(false);
  const [inviteLink, setInviteLink] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Workspace creation
  const [newWsName, setNewWsName] = useState("");
  const [newWsDesc, setNewWsDesc] = useState("");
  const [creatingWs, setCreatingWs] = useState(false);

  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [u, w, i] = await Promise.all([
        api("GET", "/admin/users"),
        api("GET", "/admin/workspaces"),
        api("GET", "/admin/invites"),
      ]);
      setUsers(u ?? []);
      setWorkspaces(w ?? []);
      setInvites(i ?? []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const openWorkspace = useCallback(async (ws: Workspace) => {
    setSelectedWorkspace(ws);
    const members = await api("GET", `/admin/workspaces/${ws.workspace_id}/members`);
    setWsMembers(members ?? []);
  }, []);

  const sendInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInviteLoading(true);
    setInviteLink(null);
    try {
      const result = await api("POST", "/admin/invites", {
        email: inviteEmail,
        org_role: inviteOrgRole,
        workspace_id: inviteWsId || null,
        workspace_role: inviteWsRole,
      });
      if (result?.detail) { setError(result.detail); return; }
      // Get the invite link
      const linkData = await api("GET", `/admin/invites/${result.invite_id}/link`);
      const fullLink = `${window.location.origin}${linkData.link}`;
      setInviteLink(fullLink);
      setInviteEmail("");
      reload();
    } catch { setError("Failed to create invite"); }
    finally { setInviteLoading(false); }
  };

  const copyLink = () => {
    if (!inviteLink) return;
    navigator.clipboard.writeText(inviteLink);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const revokeInvite = async (id: string) => {
    await api("DELETE", `/admin/invites/${id}`);
    reload();
  };

  const toggleLock = async (u: OrgUser) => {
    if (u.locked) await api("POST", `/admin/users/${u.user_id}/unlock`);
    reload();
  };

  const removeUser = async (userId: string) => {
    if (!confirm("Remove this user from the organisation?")) return;
    await api("DELETE", `/admin/users/${userId}`);
    reload();
  };

  const createWorkspace = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreatingWs(true);
    await api("POST", "/admin/workspaces", { name: newWsName, description: newWsDesc || null });
    setNewWsName(""); setNewWsDesc("");
    setCreatingWs(false);
    reload();
  };

  const removeWsMember = async (userId: string) => {
    if (!selectedWorkspace) return;
    await api("DELETE", `/admin/workspaces/${selectedWorkspace.workspace_id}/members/${userId}`);
    openWorkspace(selectedWorkspace);
  };

  const changeWsMemberRole = async (userId: string, role: string) => {
    if (!selectedWorkspace) return;
    await api("PATCH", `/admin/workspaces/${selectedWorkspace.workspace_id}/members/${userId}`, { role });
    openWorkspace(selectedWorkspace);
  };

  const addWsMember = async (userId: string) => {
    if (!selectedWorkspace) return;
    await api("POST", `/admin/workspaces/${selectedWorkspace.workspace_id}/members`, { user_id: userId, role: "reviewer" });
    openWorkspace(selectedWorkspace);
  };

  const TABS: { id: Tab; label: string; icon: typeof Users }[] = [
    { id: "users", label: "Users", icon: Users },
    { id: "workspaces", label: "Workspaces", icon: Briefcase },
    { id: "invites", label: "Pending Invites", icon: UserPlus },
    { id: "rag", label: "RAG", icon: FileText },
  ];

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="w-full">
      {/* Header */}
      <div className="flex items-center gap-4 mb-8">
        <button onClick={onBack} className="text-sm text-text-secondary hover:text-text-primary transition-colors cursor-pointer">← Back</button>
        <div>
          <h1 className="text-2xl font-serif font-bold text-text-primary flex items-center gap-2">
            <Shield className="h-5 w-5 text-accent" /> Admin Panel
          </h1>
          <p className="text-sm text-text-secondary mt-0.5">{user?.org_name}</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-8 border-b border-border">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => { setTab(id); setSelectedWorkspace(null); }}
            className={cn("flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium transition-colors cursor-pointer border-b-2 -mb-px", tab === id ? "border-accent text-text-primary" : "border-transparent text-text-secondary hover:text-text-primary")}
          >
            <Icon className="h-3.5 w-3.5" /> {label}
            {id === "invites" && invites.length > 0 && (
              <span className="ml-1 text-[10px] bg-accent/15 text-accent rounded-full px-1.5 py-0.5 font-bold">{invites.length}</span>
            )}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><Loader2 className="h-5 w-5 animate-spin text-text-secondary/40" /></div>
      ) : (
        <>
          {/* ── Users tab ── */}
          {tab === "users" && (
            <div className="space-y-6">
              <div className="rounded-xl border border-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-surface/50">
                      <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">User</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">Title / Dept</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">Role</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">Status</th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody>
                    {users.map((u) => (
                      <tr key={u.user_id} className="border-b border-border/50 last:border-0 hover:bg-surface/30">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2.5">
                            <Avatar name={u.display_name} color={u.avatar_color} />
                            <div>
                              <p className="font-medium text-text-primary">{u.display_name}</p>
                              <p className="text-xs text-text-secondary/60">{u.email}</p>
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-text-secondary">
                          {u.job_title && <p className="text-xs">{u.job_title}</p>}
                          {u.department && <p className="text-xs text-text-secondary/50">{u.department}</p>}
                        </td>
                        <td className="px-4 py-3"><RoleBadge role={u.org_role} /></td>
                        <td className="px-4 py-3">
                          {u.locked ? (
                            <span className="text-[10px] font-bold text-risk-high bg-risk-high/10 px-1.5 py-0.5 rounded border border-risk-high/30">LOCKED</span>
                          ) : (
                            <span className="text-[10px] text-risk-low">Active</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {u.user_id !== user?.user_id && (
                            <div className="flex items-center gap-2 justify-end">
                              {u.locked && (
                                <button onClick={() => toggleLock(u)} title="Unlock" className="text-text-secondary/50 hover:text-risk-low cursor-pointer transition-colors">
                                  <Unlock className="h-3.5 w-3.5" />
                                </button>
                              )}
                              <button onClick={() => removeUser(u.user_id)} title="Remove from org" className="text-text-secondary/50 hover:text-risk-high cursor-pointer transition-colors">
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ── Workspaces tab ── */}
          {tab === "workspaces" && !selectedWorkspace && (
            <div className="space-y-6">
              {/* Create workspace */}
              <form onSubmit={createWorkspace} className="rounded-xl border border-border bg-surface p-5">
                <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-4">New Workspace</h3>
                <div className="flex gap-3 flex-wrap">
                  <input value={newWsName} onChange={e => setNewWsName(e.target.value)} required placeholder="e.g. M&A – Q2 2026" className="flex-1 min-w-40 rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary/40 focus:border-accent focus:outline-none" />
                  <input value={newWsDesc} onChange={e => setNewWsDesc(e.target.value)} placeholder="Description (optional)" className="flex-1 min-w-40 rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary/40 focus:border-accent focus:outline-none" />
                  <button type="submit" disabled={creatingWs} className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50 cursor-pointer">
                    {creatingWs ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />} Create
                  </button>
                </div>
              </form>

              {/* Workspace list */}
              <div className="space-y-2">
                {workspaces.map(ws => (
                  <button key={ws.workspace_id} onClick={() => openWorkspace(ws)} className="w-full text-left rounded-xl border border-border bg-surface px-5 py-4 hover:border-accent/40 transition-all cursor-pointer flex items-center justify-between">
                    <div>
                      <p className="font-medium text-text-primary">{ws.name}</p>
                      {ws.description && <p className="text-xs text-text-secondary/60 mt-0.5">{ws.description}</p>}
                    </div>
                    <div className="flex items-center gap-3 text-text-secondary/50">
                      <span className="text-xs">{ws.member_count} member{ws.member_count !== 1 ? "s" : ""}</span>
                      <ChevronRight className="h-4 w-4" />
                    </div>
                  </button>
                ))}
                {workspaces.length === 0 && <p className="text-sm text-text-secondary/50 text-center py-8">No workspaces yet.</p>}
              </div>
            </div>
          )}

          {/* ── Workspace detail ── */}
          {tab === "workspaces" && selectedWorkspace && (
            <div className="space-y-6">
              <button onClick={() => setSelectedWorkspace(null)} className="text-sm text-text-secondary hover:text-text-primary transition-colors cursor-pointer">← All Workspaces</button>
              <h2 className="text-lg font-semibold text-text-primary">{selectedWorkspace.name}</h2>

              {/* Members */}
              <div className="rounded-xl border border-border overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-surface/50">
                      <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">Member</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-text-secondary">Role</th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody>
                    {wsMembers.map(m => (
                      <tr key={m.user_id} className="border-b border-border/50 last:border-0">
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2.5">
                            <Avatar name={m.display_name} color={m.avatar_color} />
                            <div>
                              <p className="font-medium text-text-primary">{m.display_name}</p>
                              {m.job_title && <p className="text-xs text-text-secondary/60">{m.job_title}</p>}
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <select value={m.role} onChange={e => changeWsMemberRole(m.user_id, e.target.value)} className="text-xs bg-transparent border border-border rounded px-2 py-1 text-text-secondary focus:outline-none cursor-pointer">
                            {["workspace_admin", "reviewer", "viewer"].map(r => <option key={r} value={r}>{r.replace("_", " ")}</option>)}
                          </select>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button onClick={() => removeWsMember(m.user_id)} className="text-text-secondary/40 hover:text-risk-high cursor-pointer transition-colors">
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Add existing org member */}
              <div>
                <p className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-3">Add Existing Member</p>
                <div className="flex flex-wrap gap-2">
                  {users.filter(u => !wsMembers.find(m => m.user_id === u.user_id)).map(u => (
                    <button key={u.user_id} onClick={() => addWsMember(u.user_id)} className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs text-text-secondary hover:border-accent/50 hover:text-text-primary transition-all cursor-pointer">
                      <Avatar name={u.display_name} color={u.avatar_color} size="sm" />
                      {u.display_name}
                      <Plus className="h-3 w-3" />
                    </button>
                  ))}
                  {users.filter(u => !wsMembers.find(m => m.user_id === u.user_id)).length === 0 && (
                    <p className="text-xs text-text-secondary/50">All org members are already in this workspace.</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ── Invites tab ── */}
          {tab === "invites" && (
            <div className="space-y-6">
              {/* Invite form */}
              <form onSubmit={sendInvite} className="rounded-xl border border-border bg-surface p-5 space-y-4">
                <h3 className="text-xs font-semibold uppercase tracking-widest text-text-secondary">Invite Someone</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <input type="email" required value={inviteEmail} onChange={e => setInviteEmail(e.target.value)} placeholder="colleague@firm.com" className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary placeholder:text-text-secondary/40 focus:border-accent focus:outline-none" />
                  <select value={inviteOrgRole} onChange={e => setInviteOrgRole(e.target.value)} className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none cursor-pointer">
                    <option value="member">Member</option>
                    <option value="org_admin">Org Admin</option>
                  </select>
                  <select value={inviteWsId} onChange={e => setInviteWsId(e.target.value)} className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none cursor-pointer">
                    <option value="">No workspace (org access only)</option>
                    {workspaces.map(ws => <option key={ws.workspace_id} value={ws.workspace_id}>{ws.name}</option>)}
                  </select>
                  {inviteWsId && (
                    <select value={inviteWsRole} onChange={e => setInviteWsRole(e.target.value)} className="rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none cursor-pointer">
                      <option value="reviewer">Reviewer</option>
                      <option value="viewer">Viewer</option>
                      <option value="workspace_admin">Workspace Admin</option>
                    </select>
                  )}
                </div>
                {error && <p className="text-xs text-risk-high">{error}</p>}
                <button type="submit" disabled={inviteLoading} className="flex items-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50 cursor-pointer">
                  {inviteLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />} Generate Invite Link
                </button>

                {/* Invite link result */}
                {inviteLink && (
                  <div className="rounded-lg bg-risk-low/5 border border-risk-low/20 p-4">
                    <p className="text-xs font-semibold text-risk-low mb-2">Invite link ready — copy and send it:</p>
                    <div className="flex items-center gap-2">
                      <code className="flex-1 text-xs text-text-secondary bg-surface rounded px-3 py-2 break-all">{inviteLink}</code>
                      <button onClick={copyLink} className="shrink-0 flex items-center gap-1 rounded-lg border border-border px-3 py-2 text-xs font-medium text-text-secondary hover:text-text-primary cursor-pointer transition-colors">
                        {copied ? <><Check className="h-3 w-3 text-risk-low" /> Copied</> : <><Copy className="h-3 w-3" /> Copy</>}
                      </button>
                    </div>
                    <p className="text-[10px] text-text-secondary/50 mt-2">Link expires in 48 hours. Single use.</p>
                  </div>
                )}
              </form>

              {/* Pending invites */}
              {invites.length > 0 && (
                <div>
                  <p className="text-xs font-semibold uppercase tracking-widest text-text-secondary mb-3">Pending ({invites.length})</p>
                  <div className="space-y-2">
                    {invites.map(inv => (
                      <div key={inv.invite_id} className="flex items-center justify-between rounded-lg border border-border px-4 py-3">
                        <div>
                          <p className="text-sm font-medium text-text-primary">{inv.email}</p>
                          <p className="text-xs text-text-secondary/50">
                            {inv.workspace_name ? `${inv.workspace_name} · ` : ""}{inv.workspace_role} · invited by {inv.invited_by}
                          </p>
                        </div>
                        <button onClick={() => revokeInvite(inv.invite_id)} className="text-text-secondary/40 hover:text-risk-high cursor-pointer transition-colors ml-4">
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === "rag" && <RagDocumentPanel />}
        </>
      )}
    </motion.div>
  );
}
