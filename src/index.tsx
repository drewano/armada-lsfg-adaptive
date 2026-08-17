import {
  ButtonItem,
  DropdownItem,
  Focusable,
  PanelSection,
  PanelSectionRow,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { addEventListener, callable, definePlugin, removeEventListener, toaster } from "@decky/api";
import { FaBolt } from "react-icons/fa";
import { useCallback, useEffect, useMemo, useState } from "react";
import { t } from "./i18n";

// ---------------------------------------------------------------- types

interface ProfileData {
  key: string;
  name: string;
  active_in: string[];
  enabled: boolean;
  adaptive: boolean;
  target_fps: number;
  max_multiplier: number;
  stable_cadence: boolean;
  multiplier: number;
  flow_scale: number;
  performance_mode: boolean;
  appid: string | null;
  in_config?: boolean;
  foreign?: boolean;
}

interface LayerStatus {
  bundled: {
    available: boolean;
    layer_name: string | null;
    version: string | null;
    source: string | null;
    arch: string | null;
    arch_ok: boolean;
  };
  installed: {
    lib_exists: boolean;
    arch: string | null;
    arch_ok: boolean;
    manifest_exists: boolean;
    manifest_ok: boolean;
    version: string | null;
    needs_update: boolean;
  };
}

interface Status {
  layer: LayerStatus;
  conf: { exists: boolean; valid: boolean; profiles?: number; error?: string; path: string };
  dll: { path: string | null; exists: boolean };
  panel: {
    is_armada: boolean;
    device: string | null;
    refresh_rates: number[];
    max_refresh: number | null;
  };
  host_arch: string;
  adaptive_supported: boolean;
  last_error: string | null;
}

interface GameInfo {
  appid: string;
  name: string;
  installdir: string;
  executables: { path: string; size: number }[];
  recommended: string | null;
}

interface DoctorResult {
  host_arch?: string;
  manifest?: { exists?: boolean; layer_name?: string | null; library_path?: string; lib_exists?: boolean; has_enable_environment?: boolean; error?: string };
  arch?: { lib?: string | null; expected?: string; ok?: boolean; lib_path?: string | null };
  glibc?: { system?: string | null; layer_needs?: string | null; layer_ok?: boolean | null; cli_needs?: string | null; cli_ok?: boolean | null };
  cli?: { available?: boolean; returncode?: number; output?: string; error?: string };
  conf?: { exists?: boolean; version?: number | null; version_ok?: boolean; profiles?: number; error?: string };
  error?: string;
}

// ---------------------------------------------------------------- bindings

const getDashboardState = callable<[], { status: Status; profiles: { profiles: ProfileData[]; foreign: ProfileData[] } }>("get_dashboard_state");
const installLayer = callable<[], { ok: boolean; error?: string; layer?: LayerStatus }>("install_layer");
const uninstallLayer = callable<[], { ok: boolean; error?: string }>("uninstall_layer");
const refreshAll = callable<[], { ok: boolean; error?: string; games: GameInfo[]; lossless_dll: string | null }>("refresh_all");
const getSteamGames = callable<[], { games?: GameInfo[]; cached?: boolean; ok?: boolean; error?: string }>("get_steam_games");
const getProfiles = callable<[], { profiles: ProfileData[]; foreign: ProfileData[] }>("get_profiles");
const addSteamGame = callable<[appid: string, executable: string, name: string], { ok: boolean; error?: string }>("add_steam_game");
const removeManagedProfile = callable<[key: string], { ok: boolean; error?: string }>("remove_managed_profile");
const getActiveProfileKeys = callable<[], string[]>("get_active_profile_keys");
const runDoctor = callable<[], DoctorResult>("run_doctor");

const setProfileEnabled = callable<[key: string, enabled: boolean], { ok: boolean; error?: string }>("set_profile_enabled");
const setProfileAdaptive = callable<[key: string, adaptive: boolean], { ok: boolean; error?: string }>("set_profile_adaptive");
const setProfileTargetFps = callable<[key: string, fps: number], { ok: boolean; error?: string }>("set_profile_target_fps");
const setProfileMaxMultiplier = callable<[key: string, m: number], { ok: boolean; error?: string }>("set_profile_max_multiplier");
const setProfileMultiplier = callable<[key: string, m: number], { ok: boolean; error?: string }>("set_profile_multiplier");
const setProfileFlowScale = callable<[key: string, fs: number], { ok: boolean; error?: string }>("set_profile_flow_scale");
const setProfilePerformanceMode = callable<[key: string, pm: boolean], { ok: boolean; error?: string }>("set_profile_performance_mode");
const setProfileStableCadence = callable<[key: string, sc: boolean], { ok: boolean; error?: string }>("set_profile_stable_cadence");

// ---------------------------------------------------------------- helpers

function showError(prefix: string, error?: string) {
  toaster.toast({ title: "Armada LSFG", body: `${prefix}${error ? ` : ${error}` : ""}` });
}

// Fixed FPS targets — a dropdown survives the narrow QAM panel much better
// than a slider, and these are the values that make sense against panel
// refresh rates. The current value is always offered even if not listed.
const FPS_OPTIONS = [30, 45, 60, 90, 120, 144, 240];

function fpsOptions(current: number) {
  const values = FPS_OPTIONS.includes(current)
    ? FPS_OPTIONS
    : [...FPS_OPTIONS, current].sort((a, b) => a - b);
  return values.map((v) => ({ data: v, label: `${v} FPS` }));
}

function StateLine({ ok, warn, label, detail }: { ok?: boolean; warn?: boolean; label: string; detail?: string | null }) {
  const icon = warn ? "△" : ok ? "✓" : "✗";
  return (
    <PanelSectionRow>
      <div style={{ paddingTop: "4px", paddingBottom: detail ? "2px" : "4px" }}>
        <div style={{ display: "flex", gap: "8px", fontSize: "13px" }}>
          <span style={{ color: warn ? "#e6b450" : ok ? "#7dcf6e" : "#d97777" }}>{icon}</span>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
        </div>
        {detail ? (
          <div style={{ fontSize: "12px", color: "#8a9ba8", paddingLeft: "20px", wordBreak: "break-word" }}>
            {detail}
          </div>
        ) : null}
      </div>
    </PanelSectionRow>
  );
}

// ---------------------------------------------------------------- profile editor

function ProfileEditor({ profile, running, adaptiveSupported, onChange }: { profile: ProfileData; running: boolean; adaptiveSupported: boolean; onChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const mutate = useCallback(
    async (fn: () => Promise<{ ok: boolean; error?: string }>, optimistic: () => void) => {
      setBusy(true);
      optimistic();
      try {
        const res = await fn();
        if (!res?.ok) {
          showError(t("Échec", "Failed"), res?.error);
        }
      } catch (e: any) {
        showError(t("Échec", "Failed"), String(e?.message ?? e));
      } finally {
        setBusy(false);
        onChange(); // single reload from the backend's point of truth
      }
    },
    [onChange],
  );

  return (
    <>
      <PanelSectionRow>
        <Focusable
          style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "6px", width: "100%" }}
          onClick={() => setOpen(!open)}
        >
          <span style={{ fontSize: "13px", color: "#8a9ba8", width: "12px" }}>{open ? "▾" : "▸"}</span>
          <span style={{ flex: 1, fontSize: "14px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {running ? "🟢 " : ""}
            {profile.name}
            {!profile.enabled ? t(" (off)", " (off)") : ""}
          </span>
        </Focusable>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label={t("Frame generation", "Frame generation")}
          checked={profile.enabled}
          disabled={busy}
          onChange={(v) => mutate(() => setProfileEnabled(profile.key, v), () => {})}
        />
      </PanelSectionRow>
      {open ? (
        <>
          <PanelSectionRow>
            <ToggleField
              label={t("Adaptatif", "Adaptive")}
              description={adaptiveSupported
                ? t("Ajuste le multiplicateur pour viser le FPS cible", "Adjusts the multiplier to hit the target FPS")
                : t("Non supporté par ce moteur (multiplicateur fixe)", "Not supported by this engine (fixed multiplier)")}
              checked={profile.adaptive}
              disabled={busy || !adaptiveSupported}
              onChange={(v) => mutate(() => setProfileAdaptive(profile.key, v), () => {})}
            />
          </PanelSectionRow>
          {profile.adaptive && adaptiveSupported ? (
            <>
              <PanelSectionRow>
                <DropdownItem
                  label={t("FPS cible", "Target FPS")}
                  menuLabel={t("FPS cible", "Target FPS")}
                  rgOptions={fpsOptions(profile.target_fps)}
                  selectedOption={profile.target_fps}
                  onChange={(o) => mutate(() => setProfileTargetFps(profile.key, o.data), () => {})}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <DropdownItem
                  label={t("Multiplicateur max", "Max multiplier")}
                  menuLabel={t("Multiplicateur maximum", "Maximum multiplier")}
                  rgOptions={[2, 3, 4].map((m) => ({ data: m, label: `×${m}` }))}
                  selectedOption={profile.max_multiplier}
                  onChange={(o) => mutate(() => setProfileMaxMultiplier(profile.key, o.data), () => {})}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <ToggleField
                  label={t("Cadence fluide", "Smooth cadence")}
                  description={t("Plus fluide, un peu plus de latence", "Smoother, slightly more latency")}
                  checked={profile.stable_cadence}
                  disabled={busy}
                  onChange={(v) => mutate(() => setProfileStableCadence(profile.key, v), () => {})}
                />
              </PanelSectionRow>
            </>
          ) : (
            <PanelSectionRow>
              <DropdownItem
                label={t("Multiplicateur fixe", "Fixed multiplier")}
                rgOptions={[2, 3, 4].map((m) => ({ data: m, label: `×${m}` }))}
                selectedOption={profile.multiplier}
                onChange={(o) => mutate(() => setProfileMultiplier(profile.key, o.data), () => {})}
              />
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <DropdownItem
              label="Flow Scale"
              menuLabel={t("Qualité du modèle", "Model quality")}
              rgOptions={[0.25, 0.5, 0.75, 1.0].map((s) => ({ data: s, label: s.toFixed(2) }))}
              selectedOption={profile.flow_scale}
              onChange={(o) => mutate(() => setProfileFlowScale(profile.key, o.data), () => {})}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <ToggleField
              label={t("Mode performance", "Performance mode")}
              description={t("Modèle allégé, moins de charge GPU", "Lighter model, less GPU load")}
              checked={profile.performance_mode}
              disabled={busy}
              onChange={(v) => mutate(() => setProfilePerformanceMode(profile.key, v), () => {})}
            />
          </PanelSectionRow>
          <PanelSectionRow>
            <div style={{ fontSize: "12px", color: "#8a9ba8", paddingTop: "4px", wordBreak: "break-all" }}>
              {t("Exécutables", "Executables")}: {profile.active_in.join(", ")}
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              label={t("Retirer ce jeu", "Remove this game")}
              onClick={() => mutate(() => removeManagedProfile(profile.key), () => {})}
            />
          </PanelSectionRow>
        </>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------- main content

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [profiles, setProfiles] = useState<ProfileData[]>([]);
  const [foreign, setForeign] = useState<ProfileData[]>([]);
  const [games, setGames] = useState<GameInfo[]>([]);
  const [scanProgress, setScanProgress] = useState<number | null>(null);
  const [activeKeys, setActiveKeys] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [doctor, setDoctor] = useState<DoctorResult | null>(null);

  const reloadProfiles = useCallback(async () => {
    const res = await getProfiles();
    setProfiles(res?.profiles ?? []);
    setForeign(res?.foreign ?? []);
  }, []);

  const reloadAll = useCallback(async () => {
    const dash = await getDashboardState();
    if (dash?.status) setStatus(dash.status);
    if (dash?.profiles) {
      setProfiles(dash.profiles.profiles ?? []);
      setForeign(dash.profiles.foreign ?? []);
    }
  }, []);

  const loadGames = useCallback(async () => {
    const res = await getSteamGames();
    if (res?.games) setGames(res.games);
    else if (res?.error) showError(t("Scan échoué", "Scan failed"), res.error);
  }, []);

  useEffect(() => {
    reloadAll();
    loadGames();
  }, [reloadAll, loadGames]);

  useEffect(() => {
    const listener = addEventListener<[number]>("scan_progress", (pct) => setScanProgress(pct));
    return () => removeEventListener("scan_progress", listener);
  }, []);

  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        setActiveKeys(await getActiveProfileKeys());
      } catch {
        /* plugin reloading */
      }
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  const doInstall = async () => {
    setBusy(true);
    const res = await installLayer();
    if (!res?.ok) showError(t("Installation échouée", "Install failed"), res?.error);
    else toaster.toast({ title: "Armada LSFG", body: t("Couche installée", "Layer installed") });
    await reloadAll();
    setBusy(false);
  };

  const doUninstall = async () => {
    setBusy(true);
    const res = await uninstallLayer();
    if (!res?.ok) showError(t("Désinstallation échouée", "Uninstall failed"), res?.error);
    await reloadAll();
    setBusy(false);
  };

  const doScan = async () => {
    setBusy(true);
    setScanProgress(0);
    const res = await refreshAll();
    if (res?.ok) {
      setGames(res.games ?? []);
      await reloadAll();
    } else {
      showError(t("Scan échoué", "Scan failed"), res?.error);
    }
    setScanProgress(null);
    setBusy(false);
  };

  const doDoctor = async () => {
    setBusy(true);
    try {
      setDoctor(await runDoctor());
    } catch (e: any) {
      showError(t("Diagnostic échoué", "Doctor failed"), String(e?.message ?? e));
    }
    setBusy(false);
  };

  const managedKeys = useMemo(
    () => new Set(profiles.flatMap((p) => [p.key, ...p.active_in.map((a) => a.toLowerCase())])),
    [profiles],
  );

  const addableGames = useMemo(() => {
    return games.filter((g) => {
      const rec = g.recommended?.toLowerCase();
      return !(rec && managedKeys.has(rec));
    });
  }, [games, managedKeys]);

  const layerOk = !!status?.layer.installed.lib_exists && !!status?.layer.installed.manifest_ok;

  return (
    <>
      <PanelSection title={t("Statut", "Status")}>
        {status ? (
          <>
            {status.last_error ? (
              <StateLine warn label={t("Dernière erreur", "Last error")} detail={status.last_error} />
            ) : null}
            <StateLine
              ok={status.layer.bundled.available}
              label={t("Moteur LSFG bundlé", "Bundled LSFG engine")}
              detail={status.layer.bundled.version ?? undefined}
            />
            <StateLine
              ok={status.layer.installed.lib_exists && status.layer.installed.arch_ok}
              label={t("Couche installée", "Layer installed")}
              detail={status.layer.installed.arch ?? undefined}
            />
            <StateLine ok={status.layer.installed.manifest_ok} label={t("Manifeste Vulkan", "Vulkan manifest")} />
            <StateLine ok={status.conf.valid} label="conf.toml" detail={status.conf.exists ? String(status.conf.profiles ?? "?") : undefined} />
            <StateLine
              ok={status.dll.exists}
              label="Lossless.dll"
              detail={status.dll.exists ? "✓" : t("introuvable", "not found")}
            />
            <StateLine
              warn={!status.panel.is_armada}
              ok={status.panel.is_armada}
              label={t("Appareil", "Device")}
              detail={
                status.panel.is_armada
                  ? [
                      status.panel.device ?? "Armada",
                      status.panel.refresh_rates.length
                        ? `${status.panel.refresh_rates.join("/")} Hz`
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  : t("Armada OS non détecté", "Armada OS not detected")
              }
            />
            {!status.adaptive_supported ? (
              <StateLine
                warn
                label={t("Moteur sans mode adaptatif", "Engine lacks adaptive mode")}
              />
            ) : null}
            {!layerOk ? (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={doInstall} disabled={busy || !status.layer.bundled.available}>
                  {t("Installer la couche LSFG", "Install LSFG layer")}
                </ButtonItem>
              </PanelSectionRow>
            ) : status.layer.installed.needs_update ? (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={doInstall} disabled={busy}>
                  {t("Mettre à jour la couche", "Update layer")}
                </ButtonItem>
              </PanelSectionRow>
            ) : null}
            {layerOk ? (
              <PanelSectionRow>
                <ButtonItem layout="below" onClick={doUninstall} disabled={busy}>
                  {t("Désinstaller la couche", "Uninstall layer")}
                </ButtonItem>
              </PanelSectionRow>
            ) : null}
            <PanelSectionRow>
              <ButtonItem layout="below" onClick={doDoctor} disabled={busy}>
                {t("Diagnostic complet", "Full diagnostic")}
              </ButtonItem>
            </PanelSectionRow>
            {doctor ? (
              <>
                <StateLine ok={doctor.manifest?.exists} label="Manifest" detail={doctor.manifest?.layer_name ?? doctor.manifest?.error ?? undefined} />
                <StateLine
                  ok={doctor.manifest?.lib_exists}
                  warn={doctor.manifest?.exists && !doctor.manifest?.lib_exists}
                  label={t("Librairie (manifest)", "Library (manifest)")}
                  detail={doctor.manifest?.library_path ?? undefined}
                />
                <StateLine ok={doctor.arch?.ok} label={t("Architecture", "Architecture")} detail={`${doctor.arch?.lib ?? "?"} / ${doctor.arch?.expected ?? "?"}`} />
                <StateLine
                  ok={doctor.glibc?.layer_ok === true}
                  warn={doctor.glibc?.layer_ok == null}
                  label="glibc"
                  detail={t(
                    `moteur: ${doctor.glibc?.layer_needs ?? "?"} · système: ${doctor.glibc?.system ?? "?"}`,
                    `engine: ${doctor.glibc?.layer_needs ?? "?"} · system: ${doctor.glibc?.system ?? "?"}`,
                  )}
                />
                {doctor.conf ? (
                  <StateLine
                    ok={doctor.conf.version_ok === true}
                    warn={doctor.conf.version_ok !== true}
                    label="conf.toml version"
                    detail={t(
                      `version = ${doctor.conf.version ?? "?"} (${doctor.conf.profiles ?? 0} profils)`,
                      `version = ${doctor.conf.version ?? "?"} (${doctor.conf.profiles ?? 0} profiles)`,
                    )}
                  />
                ) : null}
                {doctor.cli?.available ? (
                  <StateLine ok={doctor.cli.returncode === 0} warn={doctor.cli.returncode !== 0} label="lsfg-vk-cli validate" detail={doctor.cli.output || doctor.cli.error || `rc=${doctor.cli.returncode}`} />
                ) : (
                  <StateLine warn label={t("CLI non bundlé", "CLI not bundled")} />
                )}
                {doctor.error ? <StateLine warn label="Error" detail={doctor.error} /> : null}
              </>
            ) : null}
          </>
        ) : (
          <PanelSectionRow>{t("Chargement…", "Loading…")}</PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title={t("Jeux", "Games")}>
        {profiles.length === 0 ? (
          <PanelSectionRow>
            {t("Aucun jeu géré. Ajoute-en un ci-dessous.", "No managed games. Add one below.")}
          </PanelSectionRow>
        ) : (
          profiles.map((p) => (
            <ProfileEditor key={p.key} profile={p} running={activeKeys.includes(p.key)} adaptiveSupported={!!status?.adaptive_supported} onChange={reloadProfiles} />
          ))
        )}
        {foreign.length > 0 ? (
          <PanelSectionRow>
            <div style={{ fontSize: "12px", color: "#8a9ba8", paddingTop: "8px" }}>
              {t(
                `${foreign.length} profil(s) externe(s) préservé(s)`,
                `${foreign.length} foreign profile(s) preserved`,
              )}
            </div>
          </PanelSectionRow>
        ) : null}
      </PanelSection>

      <PanelSection title={t("Ajouter un jeu", "Add a game")}>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={doScan} disabled={busy}>
            {scanProgress !== null
              ? t(`Scan ${scanProgress}%`, `Scanning ${scanProgress}%`)
              : t("Rescanner la bibliothèque Steam", "Rescan Steam library")}
          </ButtonItem>
        </PanelSectionRow>
        {addableGames.length > 0 ? (
          addableGames.slice(0, 1).map((g) => (
            <PanelSectionRow key={g.appid}>
              <DropdownItem
                label={t("Jeu à ajouter", "Game to add")}
                menuLabel={t("Choisis un jeu installé", "Pick an installed game")}
                strDefaultLabel="—"
                rgOptions={addableGames.map((game) => ({
                  data: game.appid,
                  label: `${game.name} (${game.executables.length} exe)`,
                }))}
                selectedOption={-1}
                onChange={async (option) => {
                  const game = addableGames.find((x) => x.appid === option.data);
                  if (!game?.recommended) {
                    showError(t("Aucun exécutable trouvé", "No executable found"));
                    return;
                  }
                  const res = await addSteamGame(game.appid, game.recommended, game.name);
                  if (res?.ok) {
                    await reloadProfiles();
                    toaster.toast({ title: "Armada LSFG", body: `${game.name} ✓` });
                  } else {
                    showError(t("Ajout échoué", "Add failed"), res?.error);
                  }
                }}
              />
            </PanelSectionRow>
          ))
        ) : (
          <PanelSectionRow>
            {t(
              "Tous les jeux détectés sont déjà gérés (ou bibliothèque vide).",
              "All detected games are already managed (or library is empty).",
            )}
          </PanelSectionRow>
        )}
      </PanelSection>
    </>
  );
}

// ---------------------------------------------------------------- plugin

export default definePlugin(() => {
  return {
    name: "Armada LSFG Adaptive",
    titleView: <div className={staticClasses.Title}>Armada LSFG Adaptive</div>,
    icon: <FaBolt />,
    content: <Content />,
    onDismount() {},
  };
});
