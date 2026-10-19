import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { Zone } from "../types";
import { Icon } from "../components/Icon";

const emptyForm = {
  name: "",
  latitude: "",
  longitude: "",
  crop_type: "",
  soil_type: "",
  moisture_threshold: "40",
  target_moisture: "60",
  enabled: true,
};

export const Zones: React.FC = () => {
  const [zones, setZones] = useState<Zone[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editZone, setEditZone] = useState<Zone | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Zone | null>(null);

  const loadZones = async () => {
    const { zones: list } = await api.zones.list();
    setZones(list);
    setLoading(false);
  };

  useEffect(() => { loadZones(); }, []);

  const openCreate = () => {
    setEditZone(null);
    setForm(emptyForm);
    setFormError(null);
    setShowForm(true);
  };

  const openEdit = (zone: Zone) => {
    setEditZone(zone);
    setForm({
      name: zone.name,
      latitude: String(zone.latitude),
      longitude: String(zone.longitude),
      crop_type: zone.crop_type,
      soil_type: zone.soil_type,
      moisture_threshold: String(zone.moisture_threshold),
      target_moisture: String(zone.target_moisture),
      enabled: zone.enabled,
    });
    setFormError(null);
    setShowForm(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    const payload = {
      name: form.name,
      latitude: parseFloat(form.latitude),
      longitude: parseFloat(form.longitude),
      crop_type: form.crop_type,
      soil_type: form.soil_type,
      moisture_threshold: parseFloat(form.moisture_threshold),
      target_moisture: parseFloat(form.target_moisture),
      enabled: form.enabled,
    };
    try {
      if (editZone) {
        await api.zones.update(editZone.zone_id, payload);
      } else {
        await api.zones.create(payload);
      }
      setShowForm(false);
      await loadZones();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!deleteTarget) return;
    await api.zones.delete(deleteTarget.zone_id);
    setDeleteTarget(null);
    await loadZones();
  };

  if (loading) return <div className="page-loading"><div className="spinner" /></div>;

  return (
    <div className="zones-page">
      <div className="section-header">
        <h1 className="page-title">Zones</h1>
        <button className="btn-primary" onClick={openCreate} id="create-zone-btn">
          <Icon name="plus" size={14} />
          New zone
        </button>
      </div>

      {zones.length === 0 ? (
        <div className="dashboard__empty">
          <p>No zones yet. Create your first agricultural zone above.</p>
        </div>
      ) : (
        <div className="zones-table-wrap">
          <table className="zones-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Crop</th>
                <th>Soil</th>
                <th>Threshold</th>
                <th>Target</th>
                <th>Coords</th>
                <th>Status</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {zones.map((zone) => (
                <tr key={zone.zone_id}>
                  <td><strong>{zone.name}</strong><br /><small>{zone.zone_id}</small></td>
                  <td>{zone.crop_type}</td>
                  <td>{zone.soil_type}</td>
                  <td>{zone.moisture_threshold}%</td>
                  <td>{zone.target_moisture}%</td>
                  <td>{zone.latitude.toFixed(3)}, {zone.longitude.toFixed(3)}</td>
                  <td>
                    <span className={zone.enabled ? "badge badge-ok" : "badge badge-disabled"}>
                      {zone.enabled ? "Enabled" : "Disabled"}
                    </span>
                  </td>
                  <td>
                    <div className="zones-table__actions">
                      <button className="btn-icon" onClick={() => openEdit(zone)} id={`edit-zone-${zone.zone_id}`} aria-label={`Edit ${zone.name}`}>
                        <Icon name="pencil" size={15} />
                      </button>
                      <button className="btn-icon btn-icon--danger" onClick={() => setDeleteTarget(zone)} id={`delete-zone-${zone.zone_id}`} aria-label={`Delete ${zone.name}`}>
                        <Icon name="trash" size={15} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Create/Edit modal */}
      {showForm && (
        <div className="modal-overlay" onClick={() => setShowForm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2 className="modal__title">{editZone ? `Edit ${editZone.name}` : "New zone"}</h2>
            <form onSubmit={handleSave} className="modal__form">
              {(["name", "crop_type", "soil_type"] as const).map((field) => (
                <label key={field} className="sensor-form__label">
                  {field.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                  <input
                    id={`zone-form-${field}`}
                    type="text"
                    className="sensor-form__input"
                    value={form[field] as string}
                    onChange={(e) => setForm((f) => ({ ...f, [field]: e.target.value }))}
                    required
                  />
                </label>
              ))}
              {(["latitude", "longitude", "moisture_threshold", "target_moisture"] as const).map((field) => (
                <label key={field} className="sensor-form__label">
                  {field.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                  <input
                    id={`zone-form-${field}`}
                    type="number"
                    step="any"
                    className="sensor-form__input"
                    value={form[field] as string}
                    onChange={(e) => setForm((f) => ({ ...f, [field]: e.target.value }))}
                    required
                  />
                </label>
              ))}
              <label className="sensor-form__label" style={{ flexDirection: "row", gap: "0.5rem", alignItems: "center" }}>
                <input
                  id="zone-form-enabled"
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
                />
                Enabled
              </label>
              {formError && <p className="sensor-form__error">{formError}</p>}
              <div className="modal__actions">
                <button type="submit" className="btn-primary" disabled={saving} id="zone-form-save">
                  {saving ? "Saving…" : "Save"}
                </button>
                <button type="button" className="btn-secondary" onClick={() => setShowForm(false)} id="zone-form-cancel">
                  Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Delete confirm */}
      {deleteTarget && (
        <div className="modal-overlay" onClick={() => setDeleteTarget(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2 className="modal__title">Delete Zone</h2>
            <p>Are you sure you want to delete <strong>{deleteTarget.name}</strong>? This cannot be undone.</p>
            <div className="modal__actions">
              <button className="btn-danger" onClick={handleDelete} id="confirm-delete-zone">Delete</button>
              <button className="btn-secondary" onClick={() => setDeleteTarget(null)} id="cancel-delete-zone">Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
