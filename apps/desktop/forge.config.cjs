const path = require("node:path");
const { FusesPlugin } = require("@electron-forge/plugin-fuses");
const { FuseV1Options, FuseVersion } = require("@electron/fuses");

const sidecarBundle = path.join(__dirname, "resources", "sidecars", `${process.platform}-${process.arch}`);
const iconRoot = path.join(__dirname, "resources", "icons", "bento");
const isMacSigning = process.env.BENTO_MAC_SIGNING === "1";
const isWindowsSigning = process.env.BENTO_WINDOWS_SIGNING === "1";

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is required when release signing is enabled`);
  return value;
}

const macSigning = isMacSigning ? {
  osxSign: { identity: required("APPLE_SIGNING_IDENTITY") },
  osxNotarize: {
    appleId: required("APPLE_ID"),
    appleIdPassword: required("APPLE_APP_SPECIFIC_PASSWORD"),
    teamId: required("APPLE_TEAM_ID"),
  },
} : {};
const windowsSigning = isWindowsSigning ? {
  windowsSign: {
    certificateFile: required("WINDOWS_CERTIFICATE_FILE"),
    certificatePassword: required("WINDOWS_CERTIFICATE_PASSWORD"),
  },
} : {};

module.exports = {
  outDir: path.resolve(__dirname, "../../dist/desktop"),
  packagerConfig: {
    asar: true,
    executableName: "bento",
    appBundleId: "app.bento.desktop",
    appCategoryType: "public.app-category.productivity",
    icon: process.platform === "darwin" ? `${iconRoot}.icns` : process.platform === "win32" ? `${iconRoot}.ico` : `${iconRoot}.png`,
    ...macSigning,
    ...windowsSigning,
    extraResource: [path.join(sidecarBundle, "bento-sidecar")],
    ignore: [
      /^\/src($|\/)/,
      /^\/tests($|\/)/,
      /^\/scripts($|\/)/,
      /^\/resources($|\/)/,
      /^\/node_modules\/\.cache($|\/)/,
    ],
  },
  makers: [
    {
      name: "@electron-forge/maker-squirrel",
      platforms: ["win32"],
      config: {
        name: "bento",
        setupIcon: `${iconRoot}.ico`,
        ...(isWindowsSigning ? {
          certificateFile: required("WINDOWS_CERTIFICATE_FILE"),
          certificatePassword: required("WINDOWS_CERTIFICATE_PASSWORD"),
        } : {}),
      },
    },
    { name: "@electron-forge/maker-dmg", platforms: ["darwin"], config: { format: "ULFO", icon: `${iconRoot}.icns` } },
    { name: "@electron-forge/maker-zip", platforms: ["darwin", "linux"] },
    {
      name: "@electron-forge/maker-deb",
      platforms: ["linux"],
      config: { options: { maintainer: "Bento", homepage: "https://github.com/invrnt/bento", categories: ["Utility"], bin: "bento", icon: `${iconRoot}.png` } },
    },
  ],
  plugins: [
    new FusesPlugin({
      version: FuseVersion.V1,
      [FuseV1Options.RunAsNode]: false,
      [FuseV1Options.EnableCookieEncryption]: true,
      [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,
      [FuseV1Options.EnableNodeCliInspectArguments]: false,
      [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,
      [FuseV1Options.OnlyLoadAppFromAsar]: true,
    }),
  ],
};
