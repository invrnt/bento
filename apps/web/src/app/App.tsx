import { useEffect, useMemo, useState } from "react";

import { AppShell } from "../components/AppShell";
import { resolveRoute, navItems } from "../routes/routeConfig";
import { AlbumDetailRoute } from "../routes/albumsDetail";
import { AlbumsRoute } from "../routes/albums";
import { DocumentsRoute } from "../routes/documents";
import { DriveRoute } from "../routes/drive";
import { FavoritesRoute } from "../routes/favorites";
import { JobsRoute } from "../routes/jobs";
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
  const pathname = location.pathname;
  const route = useMemo(() => resolveRoute(pathname), [pathname]);

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

  useEffect(() => {
    document.title = `${t(route.titleKey)} · ${t("app.brand")}`;
  }, [route.titleKey]);

  function navigate(href: string) {
    window.history.pushState({}, "", href);
    setLocation(currentLocation());
  }

  function submitSearch(query: string) {
    const params = query.trim() ? `?q=${encodeURIComponent(query.trim())}` : "";
    navigate(`/search${params}`);
  }

  return (
    <AppShell
      activePath={pathname}
      navItems={navItems}
      onNavigate={navigate}
      onSearch={submitSearch}
      status={<ConnectedGlobalJobStatusIndicator onNavigate={navigate} />}
    >
      <RouteContent pathname={pathname} routeKey={route.titleKey} urlKey={`${pathname}${location.search}`} />
    </AppShell>
  );
}

function currentLocation() {
  return {
    pathname: window.location.pathname,
    search: window.location.search,
  };
}

function RouteContent({ pathname, routeKey, urlKey }: { pathname: string; routeKey: string; urlKey: string }) {
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
      return <SettingsRoute />;
    default:
      return <RoutePlaceholder bodyKey="route.notFound.body" titleKey="route.notFound.title" />;
  }
}
