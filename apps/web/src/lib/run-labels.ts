/** `provider_sync_runs.endpoint` -> words people use. Safe to import from server components. */
export const ENDPOINT_LABELS: Record<string, string> = {
  cost_report: "Costs",
  cost_total: "Costs (provider total)",
  analytics_cost: "Costs and usage",
  analytics_total: "Costs (provider total)",
  usage_report_messages: "Usage",
  costs: "Costs",
  costs_total: "Costs (provider total)",
  costs_by_key: "Costs by API key (provider total)",
  usage_completions: "Usage: completions",
  allocation: "Allocation",
  anomaly_detection: "Anomalies",
  projection: "Projection",
  budget_evaluation: "Budgets",
  api_keys: "Inventory: API keys",
  keys: "Inventory: API keys",
  workspaces: "Inventory: workspaces",
  workspace_members: "Inventory: members",
  users: "Inventory: users",
  organization_members: "Inventory: users",
  projects: "Inventory: projects",
  project_api_keys: "Inventory: API keys",
  service_accounts: "Inventory: service accounts",
  project_users: "Inventory: project members",
};

export function endpointLabel(endpoint: string): string {
  return ENDPOINT_LABELS[endpoint] ?? endpoint;
}
