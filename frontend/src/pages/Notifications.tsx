import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../services/api";
import type { ActivityEvent, Subscriber, SystemStatus, Zone } from "../types";
import { Icon } from "../components/Icon";
import { clockTime, timeAgo } from "../utils/time";

const POLL_MS = 5000;

export const Notifications: React.FC = () => {
  const [zones, setZones] = useState<Zone[]>([]);
  const [subs, setSubs] = useState<Subscriber[]>([]);
  const [emails, setEmails] = useState<ActivityEvent[]>([]);
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [openEmail, setOpenEmail] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [allZones, setAllZones] = useState(true);
  const [picked, setPicked] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [formMsg, setFormMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const [z, s, e, st] = await Promise.allSettled([
      api.zones.list(),
      api.subscribers.list(),
      api.system.activity("email", 40),
      api.system.status(),
    ]);
    if (z.status === "fulfilled") setZones([...z.value.zones].sort((a, b) => a.name.localeCompare(b.name)));
    if (s.status === "fulfilled") setSubs(s.value.subscribers);
    if (e.status === "fulfilled") setEmails(e.value.events);
    if (st.status === "fulfilled") setStatus(st.value);
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_MS);
    return () => clearInterval(id);
  }, [load]);

  const register = async (ev: FormEvent) => {
    ev.preventDefault();
    setSaving(true);
    setFormMsg(null);
    try {
      const { welcome_email } = await api.subscribers.create({
        name,
        email,
        zone_ids: allZones ? ["*"] : picked,
      });
      setFormMsg({
        ok: true,
        text: welcome_email.status === "sent"
          ? `Registered. A welcome email is on its way to ${email}.`
          : welcome_email.status === "simulated"
            ? "Registered. Welcome email simulated (no Gmail sender configured)."
            : `Registered, but the welcome email failed (${welcome_email.error}).`,
      });
      setName("");
      setEmail("");
      setPicked([]);
      setAllZones(true);
      load();
    } catch (err: unknown) {
      setFormMsg({ ok: false, text: err instanceof Error ? err.message : "Registration failed" });
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: string) => {
    await api.subscribers.delete(id);
    load();
  };

  const zoneLabel = (ids: string[]) =>
    ids.includes("*") ? "All zones" : ids.map((id) => zones.find((z) => z.zone_id === id)?.name ?? id).join(", ");

  const simulated = status?.email.mode === "mock";

  return (
    <div className="notifications">
      <div className="section-header">
        <div>
          <h1 className="page-title">Email alerts</h1>
          <p className="page-subtitle">
            Register a Gmail address to receive an email whenever a zone needs irrigation, alongside the SMS sent through Amazon SNS.
            Each email includes the sensor reading, the weather forecast and what to do.
          </p>
        </div>
        <span className={`mode-pill${simulated ? " mode-pill--sim" : ""}`}>
          <Icon name="mail" size={13} />
          {status ? (simulated ? "Simulated delivery" : `Sending from ${status.email.sender}`) : "…"}
        </span>
      </div>

      {simulated && (
        <div className="setup-hint">
          <Icon name="key" size={14} />
          <span>
            Emails are simulated because no sender is configured. Add <code>SMTP_USER</code> (your Gmail address) and{" "}
            <code>SMTP_APP_PASSWORD</code> (a Google App Password) to <code>.env</code> and restart the backend to send real emails.
          </span>
        </div>
      )}

      <div className="notif-grid">
        {/* Registration */}
        <section className="card">
          <h2 className="card__title">Register for alerts</h2>
          <form className="reg-form" onSubmit={register}>
            <label className="sensor-form__label">
              Name
              <input className="sensor-form__input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Farm manager" required maxLength={80} />
            </label>
            <label className="sensor-form__label">
              Gmail address
              <input className="sensor-form__input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@gmail.com" required />
            </label>
            <fieldset className="zone-picker">
              <legend>Zones</legend>
              <label className="check">
                <input type="checkbox" checked={allZones} onChange={(e) => setAllZones(e.target.checked)} />
                All zones
              </label>
              {!allZones && zones.map((z) => (
                <label key={z.zone_id} className="check">
                  <input
                    type="checkbox"
                    checked={picked.includes(z.zone_id)}
                    onChange={(e) => setPicked((p) => (e.target.checked ? [...p, z.zone_id] : p.filter((x) => x !== z.zone_id)))}
                  />
                  {z.name}
                </label>
              ))}
            </fieldset>
            <button className="btn-primary" type="submit" disabled={saving || (!allZones && picked.length === 0)}>
              <Icon name="mail" size={14} />
              {saving ? "Registering…" : "Register"}
            </button>
            {formMsg && <p className={formMsg.ok ? "form-ok" : "sensor-form__error"}>{formMsg.text}</p>}
          </form>

          <h3 className="card__subtitle">Subscribers · {subs.length}</h3>
          {subs.length === 0 ? (
            <p className="muted">Nobody registered yet.</p>
          ) : (
            <ul className="sub-list">
              {subs.map((s) => (
                <li key={s.subscriber_id}>
                  <span className="sub-list__avatar">{s.name.charAt(0).toUpperCase()}</span>
                  <div className="sub-list__main">
                    <strong>{s.name}</strong>
                    <span>{s.email} · {zoneLabel(s.zone_ids)}</span>
                  </div>
                  <button className="btn-icon btn-icon--danger" onClick={() => remove(s.subscriber_id)} aria-label={`Remove ${s.name}`}>
                    <Icon name="trash" size={15} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Email outbox */}
        <section className="card">
          <div className="card__head">
            <h2 className="card__title">Email outbox</h2>
            <span className="muted">{emails.length} recent</span>
          </div>
          {emails.length === 0 ? (
            <p className="muted">No emails yet. They appear here when someone registers or an alert fires.</p>
          ) : (
            <ul className="outbox">
              {emails.map((e) => (
                <li key={e.event_id} className={openEmail === e.event_id ? "outbox__item outbox__item--open" : "outbox__item"}>
                  <button className="outbox__row" onClick={() => setOpenEmail(openEmail === e.event_id ? null : e.event_id)}>
                    <span className={`outbox__icon outbox__icon--${e.kind}`}><Icon name={e.kind === "alert" ? "bell" : "mail"} size={14} /></span>
                    <div className="outbox__main">
                      <strong>{e.subject}</strong>
                      <span>to {e.target} · {clockTime(e.created_at)} · {timeAgo(e.created_at)}</span>
                    </div>
                    <span className={`status-tag status-tag--${e.status}`}>{e.status}</span>
                  </button>
                  {openEmail === e.event_id && <pre className="outbox__body">{e.message}</pre>}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
};
