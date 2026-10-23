import React from "react";
import { ArrowUpRight, Network, Monitor, Package, BookOpen } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardAction, CardContent, CardFooter } from "./components/ui/card";
import { Button } from "./components/ui/button";
import { Badge } from "./components/ui/badge";

const tools = [
  { id: "active-directory", title: "Active Directory", icon: Network, tag: "Identity", description: "Explore users, computers and memberships.", action: "Browse directory" },
  { id: "admin", title: "Device diagnostics", icon: Monitor, tag: "Devices", description: "Inspect uptime, storage and running processes.", action: "Inspect a device" },
  { id: "packages", title: "Software catalogue", icon: Package, tag: "Software", description: "Find packages, versions and deployment details.", action: "Find a package" },
  { id: "knowledge", title: "Knowledge Base", icon: BookOpen, tag: "Knowledge", description: "Keep diagrams and support notes close at hand.", action: "Open knowledge base" },
];
function openTool(id) {
  const control = id === "knowledge"
    ? document.querySelector('.atlas-primary-nav [data-section="knowledge"]')
    : document.querySelector(`.console-sidebar [data-page="${id}"]`);
  control?.click();
}
export function WorkspaceStart() {
  return tools.map(({ id, title, icon: Icon, tag, description, action }) => (
    <Card key={id} data-workspace-tool={id}>
      <CardHeader>
        <CardTitle role="heading" aria-level={3}><Icon aria-hidden="true" />{title}</CardTitle>
        <CardAction><Badge variant="secondary">{tag}</Badge></CardAction>
      </CardHeader>
      <CardContent><CardDescription>{description}</CardDescription></CardContent>
      <CardFooter><Button variant="outline" size="sm" onClick={() => openTool(id)}>{action}<ArrowUpRight data-icon="inline-end" aria-hidden="true" /></Button></CardFooter>
    </Card>
  ));
}
