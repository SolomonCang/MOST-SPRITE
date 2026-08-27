import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { AdminPage } from "./pages/AdminPage";
import { DataPage } from "./pages/DataPage";
import { EngineeringPage } from "./pages/EngineeringPage";
import { ObservePage } from "./pages/ObservePage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/observe" replace />} />
        <Route path="observe" element={<ObservePage />} />
        <Route path="data" element={<DataPage />} />
        <Route path="engineering" element={<EngineeringPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="*" element={<Navigate to="/observe" replace />} />
      </Route>
    </Routes>
  );
}
