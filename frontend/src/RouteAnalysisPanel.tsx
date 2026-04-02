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
import { routePanelWidth, analysisPanelWidth } from "@/constants.ts";
import {
  getRouteScores,
  routeScoreLabels,
  type RouteScores,
} from "@/route-metrics.ts";
import { getRouteColor } from "@/utils.ts";

type ScoreAxis = keyof RouteScores;

interface RouteAnalysisPanelProps {
  routes: RouteFeatureCollection;
  selectedRouteIndex: number | null;
  onClose: () => void;
  style?: CSSProperties;
  top?: number;
  left?: number;
  maxHeight?: string;
}

interface RouteScoreSummary {
  routeIndex: number;
  routeLabel: string;
  color: string;
  snowFreeScore: number;
  flatScore: number;
  scenicScore: number;
  selected: boolean;
}

type TooltipValue = string | number | readonly (string | number)[] | undefined;

const getRouteLabel = (route: RouteFeature, routeCount: number) => {
  if (routeCount === 1) {
    return "Route";
  }

  if (route.properties.pareto_rank != null) {
    return `Route ${String(route.properties.pareto_rank)}`;
  }

  return `Route ${String(route.properties.route_index + 1)}`;
};

const buildRouteAnalysisData = (
  routeCollection: RouteFeatureCollection,
  selectedRouteIndex: number | null,
): RouteScoreSummary[] =>
  routeCollection.features
    .filter((route) => route.properties.penalty_breakdown != null)
    .map((route) => {
      const routeIndex = route.properties.route_index;
      const routeScores = getRouteScores(route);

      return {
        routeIndex,
        routeLabel: getRouteLabel(route, routeCollection.features.length),
        color: getRouteColor(routeIndex),
        ...routeScores,
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

const RouteScoreScatterPlot = ({
  data,
  title,
  xKey,
  yKey,
}: {
  data: RouteScoreSummary[];
  title: string;
  xKey: ScoreAxis;
  yKey: ScoreAxis;
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
          value: routeScoreLabels[xKey],
          position: "insideBottom",
          offset: -10,
        }}
        name={routeScoreLabels[xKey]}
        domain={[0, 100]}
        tickFormatter={formatPercentTick}
      />
      <YAxis
        type="number"
        dataKey={yKey}
        label={{
          value: routeScoreLabels[yKey],
          position: "insideLeft",
          textAnchor: "middle",
          angle: -90,
          offset: 5,
        }}
        name={routeScoreLabels[yKey]}
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

export const RouteAnalysisPanel = ({
  routes,
  selectedRouteIndex,
  onClose,
  style,
  top = 12,
  left = routePanelWidth + 20,
  maxHeight = "calc(100dvh - 90px)",
}: RouteAnalysisPanelProps) => {
  const analysisData = buildRouteAnalysisData(routes, selectedRouteIndex);
  const routeCount = routes.features.length;

  return (
    <Paper
      shadow="xs"
      radius="md"
      pos="absolute"
      top={top}
      left={left}
      w={analysisPanelWidth}
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
              <Title order={2}>
                Route {routeCount === 1 ? "Analysis" : "Comparison"}
              </Title>
              <Text size="sm" c="dimmed">
                Higher is better
              </Text>
            </Box>
            <ActionIcon
              variant="subtle"
              onClick={onClose}
              aria-label={`Close route ${routeCount === 1 ? "analysis" : "comparison"}`}
            >
              <IconX size="1rem" />
            </ActionIcon>
          </Group>

          {analysisData.length > 0 ? (
            <Stack gap="md">
              <Group gap="xs" wrap="wrap">
                {analysisData.map((route) => (
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
                        Selected
                      </Badge>
                    )}
                  </Group>
                ))}
              </Group>

              <Paper withBorder radius="md" p="md">
                <Text fw={600} mb="xs">
                  Score {routeCount === 1 ? "Analysis" : "Comparison"}
                </Text>
                <BarChart
                  responsive
                  data={analysisData}
                  style={{ width: "100%", aspectRatio: 1.55 }}
                >
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="routeLabel" />
                  <YAxis domain={[0, 100]} tickFormatter={formatPercentTick} />
                  <RechartsTooltip formatter={formatTooltipValue} />
                  <Legend />
                  {/* TODO Match the fill colors to the score badge colors */}
                  <Bar
                    dataKey="flatScore"
                    name={routeScoreLabels.flatScore}
                    fill="#2b8a3e"
                    radius={[6, 6, 0, 0]}
                    barSize={15}
                  />
                  <Bar
                    dataKey="scenicScore"
                    name={routeScoreLabels.scenicScore}
                    fill="#f08c00"
                    radius={[6, 6, 0, 0]}
                    barSize={15}
                  />
                  <Bar
                    dataKey="snowFreeScore"
                    name={routeScoreLabels.snowFreeScore}
                    fill="#1c7ed6"
                    radius={[6, 6, 0, 0]}
                    barSize={15}
                  />
                </BarChart>
              </Paper>

              <RouteScoreScatterPlot
                data={analysisData}
                title="Flat vs Snow-free"
                xKey="flatScore"
                yKey="snowFreeScore"
              />
              <RouteScoreScatterPlot
                data={analysisData}
                title="Flat vs Scenic"
                xKey="flatScore"
                yKey="scenicScore"
              />
              <RouteScoreScatterPlot
                data={analysisData}
                title="Snow-free vs Scenic"
                xKey="snowFreeScore"
                yKey="scenicScore"
              />
            </Stack>
          ) : (
            <Text size="sm" c="dimmed">
              Route {routeCount === 1 ? "analysis" : "comparison"} is not
              available for the current result.
            </Text>
          )}
        </Box>
      </ScrollArea.Autosize>
    </Paper>
  );
};
