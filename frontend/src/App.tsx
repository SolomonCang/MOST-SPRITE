import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { SystemShell } from "./components/SystemShell";
import { WorkspaceShell } from "./components/WorkspaceShell";
import { AdminPage } from "./pages/AdminPage";
import { DataPage } from "./pages/DataPage";
import { EngineeringPage } from "./pages/EngineeringPage";
import { ObservePage } from "./pages/ObservePage";
import { ProcessingStagePage } from "./pages/ProcessingStagePage";
import { SpectrumViewerPage } from "./pages/SpectrumViewerPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/admin" replace />} />
        <Route path="admin" element={<SystemShell />}><Route index element={<AdminPage />} /></Route>
        <Route path="observe" element={<WorkspaceShell workspace="observe" />}><Route index element={<ObservePage />} /></Route>
        <Route path="engineering" element={<WorkspaceShell workspace="engineering" />}><Route index element={<EngineeringPage />} /></Route>
        <Route path="data" element={<WorkspaceShell workspace="data" />}>
          <Route index element={<DataPage />} />
          <Route path="runs/:runId/stages/:stageKey" element={<ProcessingStagePage />} />
          <Route path="products/:productId/spectrum" element={<SpectrumViewerPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Route>
    </Routes>
  );
}
