import "./redesign/react-global.js";
import "./redesign/backend.js";
import "./redesign/tweaks-panel.jsx";
import "./redesign/AppCore.jsx";
import "./redesign/Screens.jsx";
import "./redesign/VerdictView.jsx";
import "./redesign/MoreScreens.jsx";
import "./redesign/AdminScreen.jsx";
import "./redesign/AuthScreen.jsx";

export default function RedesignHost() {
  const ActiveApp = window.App;
  return ActiveApp ? <ActiveApp /> : null;
}
