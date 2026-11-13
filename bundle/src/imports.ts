// The import map for custom components: what `import ... from "..."` resolves
// to inside an app's JSX. Adding a module is a minor version; removing one
// is a major (design decision 6).

import * as React from "react";
import * as Button from "@/components/ui/button";
import * as Input from "@/components/ui/input";
import * as Card from "@/components/ui/card";
import * as Badge from "@/components/ui/badge";
import * as Separator from "@/components/ui/separator";
import * as Spinner from "@/components/ui/spinner";
import * as Dialog from "@/components/ui/dialog";
import * as Tabs from "@/components/ui/tabs";
import * as Select from "@/components/ui/select";
import * as Checkbox from "@/components/ui/checkbox";
import * as Switch from "@/components/ui/switch";
import * as Textarea from "@/components/ui/textarea";
import * as Label from "@/components/ui/label";
import * as Tooltip from "@/components/ui/tooltip";
import * as Table from "@/components/ui/table";
import * as Skeleton from "@/components/ui/skeleton";
import * as Progress from "@/components/ui/progress";
import * as Alert from "@/components/ui/alert";
import * as Empty from "@/components/ui/empty";
import * as Collapsible from "@/components/ui/collapsible";
import * as Accordion from "@/components/ui/accordion";
import * as DropdownMenu from "@/components/ui/dropdown-menu";
import * as ScrollArea from "@/components/ui/scroll-area";
import * as Toast from "@/components/ui/toast";
import { cn } from "cn";
import { lucideForComponents } from "./icons";

export const imports: Record<string, unknown> = {
  react: React,
  "lucide-react": lucideForComponents,
  cn: { cn },
  "@/components/ui/button": Button,
  "@/components/ui/input": Input,
  "@/components/ui/card": Card,
  "@/components/ui/badge": Badge,
  "@/components/ui/separator": Separator,
  "@/components/ui/spinner": Spinner,
  "@/components/ui/dialog": Dialog,
  "@/components/ui/tabs": Tabs,
  "@/components/ui/select": Select,
  "@/components/ui/checkbox": Checkbox,
  "@/components/ui/switch": Switch,
  "@/components/ui/textarea": Textarea,
  "@/components/ui/label": Label,
  "@/components/ui/tooltip": Tooltip,
  "@/components/ui/table": Table,
  "@/components/ui/skeleton": Skeleton,
  "@/components/ui/progress": Progress,
  "@/components/ui/alert": Alert,
  "@/components/ui/empty": Empty,
  "@/components/ui/collapsible": Collapsible,
  "@/components/ui/accordion": Accordion,
  "@/components/ui/dropdown-menu": DropdownMenu,
  "@/components/ui/scroll-area": ScrollArea,
  "@/components/ui/toast": Toast,
};
