import ContractReader from "./components/ContractReader";
import ContractEditor from "./components/ContractEditor";
import "./redesign/react-global.js";
import "./redesign/backend.js";
import "./redesign/tweaks-panel.jsx";
import "./redesign/AppCore.jsx";
import "./redesign/Screens.jsx";
import "./redesign/VerdictView.jsx";
import "./redesign/MoreScreens.jsx";
import "./redesign/AdminScreen.jsx";
import "./redesign/AuthScreen.jsx";

window.ContractReader = ContractReader;
window.ContractEditor = ContractEditor;

export default function RedesignHost() {
  const ActiveApp = window.App;
  return ActiveApp ? <ActiveApp /> : null;
}
