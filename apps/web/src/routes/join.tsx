import { JoinScreen } from "../features/pairing/JoinScreen";
import type { JoinScreenProps } from "../features/pairing/JoinScreen";
import { pairingCodeFromLocation } from "../features/pairing/pairingCode";

export type JoinRouteProps = Omit<JoinScreenProps, "initialCode"> & { hash: string; search: string };

/** `/join?c=…` (or `#v=1&c=…`) opens the join screen with the code filled in. */
export function JoinRoute({ hash, search, ...props }: JoinRouteProps) {
  const initialCode = pairingCodeFromLocation(search, hash);
  return <JoinScreen initialCode={initialCode} key={initialCode} {...props} />;
}

export default JoinRoute;
