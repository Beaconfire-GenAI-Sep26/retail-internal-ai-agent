import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import "./styles.css";

const services = [
  { name: "Authentication", path: "/auth/health", docs: "/auth/docs" },
  { name: "Investigation agent", path: "/agent/health", docs: "/agent/docs" },
  { name: "Domain and database", path: "/domain/ready", docs: "/domain/docs" },
];

function ServiceStatus({ service }) {
  const [status, setStatus] = useState("Checking…");

  useEffect(() => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);

    async function checkHealth() {
      try {
        const response = await fetch(service.path, { signal: controller.signal });
        const result = await response.json();
        setStatus(response.ok && result.status === "ok" ? "Ready" : "Unavailable");
      } catch {
        setStatus("Unavailable");
      } finally {
        clearTimeout(timeout);
      }
    }

    checkHealth();
    return () => {
      controller.abort();
      clearTimeout(timeout);
    };
  }, [service.path]);

  return (
    <li>
      <div>
        <h2>{service.name}</h2>
        <a href={service.docs}>Open API documentation</a>
      </div>
      <span role="status" className={status === "Ready" ? "ready" : ""}>
        {status}
      </span>
    </li>
  );
}

function App() {
  return (
    <BrowserRouter>
      <main>
        <Routes>
          <Route
            path="/"
            element={
              <>
                <p className="eyebrow">Store order quality</p>
                <h1>DoorDash Store Diagnosis</h1>
                <p className="intro">Service availability for the analyst workspace.</p>
                <ul className="services">
                  {services.map((service) => (
                    <ServiceStatus key={service.path} service={service} />
                  ))}
                </ul>
              </>
            }
          />
          <Route
            path="*"
            element={
              <>
                <h1>Page unavailable</h1>
                <Link to="/">Return to service status</Link>
              </>
            }
          />
        </Routes>
      </main>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")).render(<App />);
