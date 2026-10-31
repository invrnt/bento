import { useCallback, useEffect, useMemo, useState } from "react";

import { AppShell } from "../components/AppShell";
import { LoadingState } from "../components/States";
import { BootstrapBanner } from "../features/onboarding/BootstrapProgress";
import { onDeepLink, onNavigate } from "../features/onboarding/desktopHost";
import { FirstRun } from "../features/onboarding/FirstRun";
import type { FirstRunProps } from "../features/onboarding/FirstRun";
import { chooseLocalMode, forgetLocalMode } from "../features/onboarding/localMode";
import { useAppGate } from "../features/onboarding/useAppGate";
import { JoinScreen } from "../features/pairing/JoinScreen";
import { PairingRequestsBanner } from "../features/pairing/PairingRequestsBanner";
import { resolveRoute, navItems } from "../routes/routeConfig";
import { AlbumDetailRoute } from "../routes/albumsDetail";
import { AlbumsRoute } from "../routes/albums";
import { DocumentsRoute } from "../routes/documents";
import { DriveRoute } from "../routes/drive";
import { FavoritesRoute } from "../routes/favorites";
import { JobsRoute } from "../routes/jobs";
import { JoinRoute } from "../routes/join";
import { PhotoDetailRoute } from "../routes/photosDetail";
import { PhotosRoute } from "../routes/photos";
import { SearchRoute } from "../routes/search";
import { SettingsRoute } from "../routes/settings";
import { RoutePlaceholder } from "../routes/RoutePlaceholder";
import { t } from "../i18n/dictionary";
import { ConnectedGlobalJobStatusIndicator } from "./status";

const defaultRoute = "/photos";

export function App() {
  const [location, setLocation] = useState(() => currentLocation());
  const { gate, refresh, setGate } = useAppGate();
  const [firstRunStart, setFirstRunStart] = useState<FirstRunProps["initialStep"]>("welcome");
  const pathname = location.pathname;
  const route = useMemo(() => resolveRoute(pathname), [pathname]);
  const onJoinRoute = route.titleKey === "route.join.title";

  const navigate = useCallback((href: string) => {
    window.history.pushState({}, "", href);
    setLocation(currentLocation());
  }, []);

  useEffect(() => {
    if (window.location.pathname === "/") {
      window.history.replaceState({}, "", defaultRoute);
      setLocation(currentLocation());
    }

    function onPopState() {
      setLocation(currentLocation());
    }

    window.addEventListener("popstate", onPopState);

    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // Desktop: `bento://join?…` links and tray/notification navigation.
  useEffect(() => onDeepLink((link) => navigate(`/join?c=${encodeURIComponent(link.code)}`)), [navigate]);
  useEffect(() => onNavigate(navigate), [navigate]);

  const showingFirstRun = gate.kind === "first-run" && !onJoinRoute;

  useEffect(() => {
    document.title = `${showingFirstRun ? t("firstRun.documentTitle") : t(route.titleKey)} · ${t("app.brand")}`;
  }, [route.titleKey, showingFirstRun]);

  function submitSearch(query: string) {
    const params = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
    navigate(`/search${params}`);
  }

  async function enterLibrary() {
    await refresh();
    navigate(defaultRoute);
  }

  async function keepLocal() {
    await chooseLocalMode();
    setGate({ kind: "app", vault: null });
    navigate(defaultRoute);
  }

  /** "Conectar mi Telegram" from Ajustes: reopen setup at the Telegram step (or unlock). */
  function startSetup() {
    forgetLocalMode();
    setFirstRunStart("telegram");
    void refresh().then((next) => {
      const member = next.kind === "app" && (next.vault?.state === "ready" || next.vault?.state === "bootstrapping");
      if (next.kind === "app" && !member) setGate({ kind: "first-run" });
    });
  }

  if (gate.kind === "loading") {
    return (
      <div className="grid min-h-dvh place-items-center bg-tray">
        <LoadingState label={t("setup.loading")} />
      </div>
    );
  }

  const member = gate.kind === "app" && (gate.vault?.state === "ready" || gate.vault?.state === "bootstrapping");

  if (onJoinRoute) {
    return (
      <JoinRoute
        alreadyMember={member}
        hash={location.hash}
        initialStep={gate.kind === "locked" ? "choose" : "code"}
        onBack={() => navigate(defaultRoute)}
        onCreateVault={() => {
          setFirstRunStart("creating");
          setGate({ kind: "first-run" });
          navigate(defaultRoute);
        }}
        onDone={() => void enterLibrary()}
        onLocalOnly={gate.kind === "app" ? undefined : () => void keepLocal()}
        search={location.search}
      />
    );
  }

  if (gate.kind === "first-run") {
    return (
      <FirstRun
        initialStep={firstRunStart}
        key={firstRunStart}
        onExistingVault={() => setGate({ kind: "locked" })}
        onFinish={() => void enterLibrary()}
        onJoin={() => navigate("/join")}
        onLocalOnly={() => {
          setGate({ kind: "app", vault: null });
          navigate(defaultRoute);
        }}
      />
    );
  }

  if (gate.kind === "locked") {
    return <JoinScreen initialStep="choose" onDone={() => void enterLibrary()} onLocalOnly={() => void keepLocal()} />;
  }

  const vaultState = gate.vault?.state;

  return (
    <AppShell
      activePath={pathname}
      navItems={navItems}
      onNavigate={navigate}
      onSearch={submitSearch}
      status={<ConnectedGlobalJobStatusIndicator onNavigate={navigate} />}
    >
      {vaultState === "bootstrapping" ? <BootstrapBanner /> : null}
      {vaultState === "ready" ? <PairingRequestsBanner /> : null}
      <RouteContent
        onNavigate={navigate}
        onStartSetup={startSetup}
        pathname={pathname}
        routeKey={route.titleKey}
        urlKey={`${pathname}${location.search}`}
      />
    </AppShell>
  );
}

function currentLocation() {
  return {
    hash: window.location.hash,
    pathname: window.location.pathname,
    search: window.location.search,
  };
}

function RouteContent({
  onNavigate: navigate,
  onStartSetup,
  pathname,
  routeKey,
  urlKey,
}: {
  onNavigate: (href: string) => void;
  onStartSetup: () => void;
  pathname: string;
  routeKey: string;
  urlKey: string;
}) {
  switch (routeKey) {
    case "route.search.title":
      return <SearchRoute key={urlKey} />;
    case "route.photos.title":
      return <PhotosRoute />;
    case "route.photoDetail.title":
      return <PhotoDetailRoute key={pathname} />;
    case "route.albums.title":
      return <AlbumsRoute />;
    case "route.albumDetail.title":
      return <AlbumDetailRoute key={pathname} />;
    case "route.favorites.title":
      return <FavoritesRoute />;
    case "route.drive.title":
    case "route.driveFolder.title":
      return <DriveRoute key={pathname} pathname={pathname} />;
    case "route.documents.title":
      return <DocumentsRoute key={urlKey} />;
    case "route.jobs.title":
      return <JobsRoute />;
    case "route.settings.title":
      return <SettingsRoute onNavigate={navigate} onStartSetup={onStartSetup} pathname={pathname} />;
    default:
      return <RoutePlaceholder bodyKey="route.notFound.body" titleKey="route.notFound.title" />;
  }
}
