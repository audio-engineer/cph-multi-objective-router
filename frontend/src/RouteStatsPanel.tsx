import type { CSSProperties } from "react";
import {
  ActionIcon,
  Badge,
  Box,
  Group,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconX } from "@tabler/icons-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Scatter,
  ScatterChart,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { RouteFeature, RouteFeatureCollection } from "@/client";
import { panelWidth, statsPanelWidth } from "@/constants.ts";
import {
  getRouteComfortScores,
  objectiveScoreLabels,
} from "@/route-metrics.ts";
import { getRouteColor } from "@/utils.ts";

type ObjectiveAxis = "snowlessComfort" | "uphillComfort" | "scenicComfort";

interface RouteStatsPanelProps {
  routes: RouteFeatureCollection;
  selectedRouteIndex: number | null;
  onClose: () => void;
  style?: CSSProperties;
  top?: number;
  left?: number;
  maxHeight?: string;
}

interface RouteStatsDatum {
  routeIndex: number;
  routeLabel: string;
  color: string;
  snowlessComfort: number;
  uphillComfort: number;
  scenicComfort: number;
  selected: boolean;
}

type TooltipValue = string | number | readonly (string | number)[] | undefined;

const objectiveLabels: Record<ObjectiveAxis, string> = {
  snowlessComfort: objectiveScoreLabels.snowlessComfort,
  uphillComfort: objectiveScoreLabels.uphillComfort,
  scenicComfort: objectiveScoreLabels.scenicComfort,
};

const getRouteLabel = (route: RouteFeature, routeCount: number) => {
  if (routeCount === 1) {
    return "Route";
  }

  if (route.properties.pareto_rank != null) {
    return `Route ${String(route.properties.pareto_rank)}`;
  }

  return `Route ${String(route.properties.route_index + 1)}`;
};

const buildRouteStatsData = (
  routeCollection: RouteFeatureCollection,
  selectedRouteIndex: number | null,
): RouteStatsDatum[] =>
  routeCollection.features
    .filter((route) => route.properties.objective_costs != null)
    .map((route) => {
      const routeIndex = route.properties.route_index;
      const comfortScores = getRouteComfortScores(route);

      return {
        routeIndex,
        routeLabel: getRouteLabel(route, routeCollection.features.length),
        color: getRouteColor(routeIndex),
        ...comfortScores,
        selected: selectedRouteIndex === routeIndex,
      };
    });

const formatPercentTick = (value: number) => `${String(Math.round(value))}%`;

const formatTooltipValue = (value: TooltipValue) => {
  const numericValue = Array.isArray(value)
    ? Number(value[0] ?? 0)
    : Number(value ?? 0);

  return formatPercentTick(numericValue);
};

const ScatterComparisonChart = ({
  data,
  title,
  xKey,
  yKey,
}: {
  data: RouteStatsDatum[];
  title: string;
  xKey: ObjectiveAxis;
  yKey: ObjectiveAxis;
}) => (
  <Paper withBorder radius="md" p="md">
    <Text fw={600} mb="xs">
      {title}
    </Text>
    <ScatterChart
      responsive
      style={{ width: "100%", aspectRatio: 1.25 }}
      margin={{ top: 10, right: 20, bottom: 10, left: 0 }}
    >
      <CartesianGrid strokeDasharray="3 3" />
      <XAxis
        type="number"
        dataKey={xKey}
        label={{
          value: objectiveLabels[xKey],
          position: "insideBottom",
          offset: -10,
        }}
        name={objectiveLabels[xKey]}
        domain={[0, 100]}
        tickFormatter={formatPercentTick}
      />
      <YAxis
        type="number"
        dataKey={yKey}
        label={{
          value: objectiveLabels[yKey],
          position: "insideLeft",
          angle: -90,
          offset: 5,
        }}
        name={objectiveLabels[yKey]}
        domain={[0, 100]}
        // width="auto"
        tickFormatter={formatPercentTick}
      />
      <RechartsTooltip
        cursor={{ strokeDasharray: "3 3" }}
        formatter={formatTooltipValue}
      />
      {data.map((route) => (
        <Scatter
          key={route.routeIndex}
          name={route.routeLabel}
          data={[route]}
          fill={route.color}
          stroke={route.selected ? "#1f2937" : route.color}
          strokeWidth={route.selected ? 2 : 1}
        />
      ))}
    </ScatterChart>
  </Paper>
);

export const RouteStatsPanel = ({
  routes,
  selectedRouteIndex,
  onClose,
  style,
  top = 12,
  left = panelWidth + 20,
  maxHeight = "calc(100dvh - 90px)",
}: RouteStatsPanelProps) => {
  const chartData = buildRouteStatsData(routes, selectedRouteIndex);

  return (
    <Paper
      shadow="xs"
      radius="md"
      pos="absolute"
      top={top}
      left={left}
      w={statsPanelWidth}
      mah={maxHeight}
      style={{
        zIndex: 1000,
        borderTopLeftRadius: 0,
        borderBottomLeftRadius: 0,
        ...style,
      }}
    >
      <ScrollArea.Autosize mah={maxHeight} offsetScrollbars>
        <Box px={20} py={18} pr={12}>
          <Group justify="space-between" align="flex-start" mb="sm">
            <Box>
              <Title order={2}>Route Statistics</Title>
              <Text size="sm" c="dimmed">
                Normalized to 0-100%, higher is better.
              </Text>
            </Box>
            <ActionIcon
              variant="subtle"
              onClick={onClose}
              aria-label="Close route statistics"
            >
              <IconX size="1rem" />
            </ActionIcon>
          </Group>

          {chartData.length > 0 ? (
            <Stack gap="md">
              <Group gap="xs" wrap="wrap">
                {chartData.map((route) => (
                  <Group key={route.routeIndex} gap={6} wrap="nowrap">
                    <Box
                      w={10}
                      h={10}
                      style={{
                        borderRadius: 999,
                        backgroundColor: route.color,
                        border: route.selected
                          ? "2px solid #1f2937"
                          : "1px solid transparent",
                      }}
                    />
                    <Text size="sm" fw={route.selected ? 600 : 500}>
                      {route.routeLabel}
                    </Text>
                    {route.selected && (
                      <Badge size="xs" variant="light">
                        Focused
                      </Badge>
                    )}
                  </Group>
                ))}
              </Group>

              <Paper withBorder radius="md" p="md">
                <Text fw={600} mb="xs">
                  Route Score Comparison
                </Text>
                <BarChart
                  responsive
                  data={chartData}
                  style={{ width: "100%", aspectRatio: 1.55 }}
                  margin={{ top: 10, right: 10, bottom: 10, left: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="routeLabel" />
                  <YAxis domain={[0, 100]} tickFormatter={formatPercentTick} />
                  <RechartsTooltip formatter={formatTooltipValue} />
                  <Legend />
                  <Bar
                    dataKey="snowlessComfort"
                    name={objectiveLabels.snowlessComfort}
                    fill="#4c6ef5"
                    radius={[6, 6, 0, 0]}
                  />
                  <Bar
                    dataKey="uphillComfort"
                    name={objectiveLabels.uphillComfort}
                    fill="#f08c00"
                    radius={[6, 6, 0, 0]}
                  />
                  <Bar
                    dataKey="scenicComfort"
                    name={objectiveLabels.scenicComfort}
                    fill="#2b8a3e"
                    radius={[6, 6, 0, 0]}
                  />
                </BarChart>
              </Paper>

              <ScatterComparisonChart
                data={chartData}
                title="Flat vs Snowless"
                xKey="uphillComfort"
                yKey="snowlessComfort"
              />
              <ScatterComparisonChart
                data={chartData}
                title="Flat vs Scenic"
                xKey="uphillComfort"
                yKey="scenicComfort"
              />
              <ScatterComparisonChart
                data={chartData}
                title="Snowless vs Scenic"
                xKey="snowlessComfort"
                yKey="scenicComfort"
              />
            </Stack>
          ) : (
            <Text size="sm" c="dimmed">
              Route statistics are not available for the current result.
            </Text>
          )}
        </Box>
      </ScrollArea.Autosize>
    </Paper>
  );
};
