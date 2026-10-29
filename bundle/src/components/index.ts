// The registry: a wire `type` to the renderer that draws it.

import type { Renderer } from "../render";
import { Code, Markdown, Page, Row, Stack, Text } from "./layout";
import { Badge, Button, Card, Input, Separator } from "./controls";
import { Header } from "./header";
import {
  Alert,
  Dialog,
  Empty,
  Grid,
  Kbd,
  Link,
  Skeleton,
  Spinner,
  Split,
  Stat,
  Tab,
  Tabs,
  Tooltip,
  ScrollArea,
} from "./surfaces";
import { Checkbox, Combobox, NumberInput, Select, Switch, Textarea } from "./inputs";
import {
  Accordion,
  AccordionItem,
  CheckboxGroup,
  Collapsible,
  RadioGroup,
  Sheet,
  Sidebar,
  Slider,
  ToggleGroup,
} from "./more";
import { Table } from "./table";
import { ButtonGroup, DatePicker, DropdownMenu, Field, MultiSelect } from "./choices";
import { Progress as TaskProgress, Steps } from "./tasks";
import { Form } from "./form";
import { Chat } from "./chat";
import { Download, FileCard, FileUpload, Image, Pdf } from "./files";
import { AreaChart, BarChart, LineChart } from "./charts";

export const registry: Record<string, Renderer> = {
  Progress: TaskProgress,
  Steps,
  Page,
  Header,
  Stack,
  Row,
  Grid,
  Text,
  Markdown,
  Code,
  Button,
  Input,
  Textarea,
  NumberInput,
  Select,
  Combobox,
  MultiSelect,
  DatePicker,
  DropdownMenu,
  ButtonGroup,
  Field,
  Checkbox,
  Switch,
  Card,
  Badge,
  Separator,
  Tabs,
  Tab,
  Dialog,
  Empty,
  Alert,
  Skeleton,
  Spinner,
  Split,
  Stat,
  Link,
  Kbd,
  Tooltip,
  ScrollArea,
  Accordion,
  AccordionItem,
  CheckboxGroup,
  Collapsible,
  RadioGroup,
  Sheet,
  Sidebar,
  Slider,
  ToggleGroup,
  Table,
  Form,
  Chat,
  FileUpload,
  FileCard,
  Image,
  Pdf,
  Download,
  BarChart,
  LineChart,
  AreaChart,
};
