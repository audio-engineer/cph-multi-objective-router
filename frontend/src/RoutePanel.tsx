import { type Ref, useImperativeHandle, useState } from "react";
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Divider,
  Group,
  Image,
  Paper,
  ScrollArea,
  SegmentedControl,
  Slider,
  Stack,
  Tabs,
  Text,
  TextInput,
  Title,
  Tooltip,
  Transition,
  UnstyledButton,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import {
  IconChartDots,
  IconChevronLeft,
  IconQuestionMark,
  IconStarFilled,
  IconTrash,
} from "@tabler/icons-react";
import type {
  RouteFeature,
  RouteFeatureCollection,
  RouteStepResponse,
} from "@/client";
import markerIconUrl from "leaflet/dist/images/marker-icon.png?url";
import type { TransportMode } from "@/types/global.ts";
import type { RouteSelectionMethod, Mode, SearchHistoryEntry } from "@/App.tsx";
import {
  buildRouteProgressionData,
  estimateRouteDurationMinutes,
  formatDuration,
  getRouteComfortScores,
  getRouteSpeedKmPerHour,
  objectiveScoreLabels,
} from "@/route-metrics.ts";
import { getRouteColor } from "@/utils.ts";
import { RouteStatsPanel } from "@/RouteStatsPanel.tsx";
import {
  CartesianGrid,
  Tooltip as RechartsTooltip,
  Line,
  LineChart,
  XAxis,
  YAxis,
  Legend,
} from "recharts";

export type PickMode = "origin" | "destination" | null;

export interface RoutePanelHandle {
  setOrigin: (origin: string) => void;
  setDestination: (destination: string) => void;
  clearAllFields: () => void;
}

interface RoutePanelProps {
  ref?: Ref<RoutePanelHandle>;
  searchByAddress: (
    origin: string,
    destination: string,
  ) => Promise<boolean> | Promise<void>;
  routes: RouteFeatureCollection | undefined;
  loading: boolean;
  selectedRoute: RouteFeature | null;
  selectedRouteIndex: number | null;
  onSelectRouteIndex: (index: number) => void;
  onBackToRouteList: () => void;
  selectedStepIndex: number | null;
  onSelectStepIndex: (index: number | null) => void;
  onTogglePickOrigin: () => void;
  onTogglePickDestination: () => void;
  onClearAll: () => void;
  hasOriginMarker: boolean;
  hasDestinationMarker: boolean;
  pickMode: PickMode;
  transportMode: TransportMode;
  onTransportModeChange: (transportMode: TransportMode) => void;
  mode: Mode;
  onModeChange: (mode: Mode) => void;
  method: RouteSelectionMethod;
  onMethodChange: (method: RouteSelectionMethod) => void;
  scenic: number;
  onScenicChange: (scenic: number) => void;
  onScenicChangeEnd: (scenic: number) => void;
  snow: number;
  onSnowChange: (snow: number) => void;
  onSnowChangeEnd: (snow: number) => void;
  uphill: number;
  onUphillChange: (uphill: number) => void;
  onUphillChangeEnd: (uphill: number) => void;
  searchHistory: SearchHistoryEntry[];
  onSelectHistoryEntry: (entry: SearchHistoryEntry) => Promise<void>;
  onClearHistory: () => void;
}

const distanceToText = (distance: number) => {
  if (distance < 1000) {
    return `${distance.toFixed(0)} m`;
  }

  return `${(distance / 1000).toFixed(1)} km`;
};

const getRouteTitle = (
  route: RouteFeature,
  routeCount: number,
  method: RouteSelectionMethod,
) => {
  if (method === "pareto") {
    const routeRank =
      route.properties.pareto_rank ?? route.properties.route_index + 1;

    return `Route ${String(routeRank)}`;
  }

  if (routeCount === 1) {
    return "Route";
  }

  return `Route ${String(route.properties.route_index + 1)}`;
};

const formatPercent = (value: number) => `${String(Math.round(value))}%`;
type TooltipValue = string | number | readonly (string | number)[] | undefined;

const formatTooltipPercent = (value: TooltipValue) => {
  const numericValue = Array.isArray(value)
    ? Number(value[0] ?? 0)
    : Number(value ?? 0);

  return formatPercent(numericValue);
};

const objectiveBadgeConfig = [
  {
    key: "uphillComfort",
    label: objectiveScoreLabels.uphillComfort,
    color: "green",
  },
  {
    key: "scenicComfort",
    label: objectiveScoreLabels.scenicComfort,
    color: "orange",
  },
  {
    key: "snowlessComfort",
    label: objectiveScoreLabels.snowlessComfort,
    color: "cyan",
  },
] as const;

const RouteObjectiveBadges = ({ route }: { route: RouteFeature }) => {
  const comfortScores = getRouteComfortScores(route);

  return (
    <Group gap={6}>
      {objectiveBadgeConfig.map((objective) => (
        <Badge
          key={objective.key}
          variant="light"
          color={objective.color}
          size="sm"
        >
          {objective.label} {formatPercent(comfortScores[objective.key])}
        </Badge>
      ))}
    </Group>
  );
};

const RouteStepList = ({
  steps,
  selectedStepIndex,
  onSelectStepIndex,
}: {
  steps: RouteStepResponse[];
  selectedStepIndex: number | null;
  onSelectStepIndex: (index: number | null) => void;
}) => (
  <Stack gap="xs">
    {steps.map((step, index) => {
      const selectedStep = index === selectedStepIndex;

      return (
        <UnstyledButton
          key={`${step.street}-${String(index)}`}
          onClick={() => {
            if (selectedStep) {
              onSelectStepIndex(null);

              return;
            }

            onSelectStepIndex(index);
          }}
          w="100%"
        >
          <Paper
            withBorder
            p="xs"
            radius="sm"
            bg={selectedStep ? "rgba(0,0,0,0.06)" : undefined}
          >
            <Group justify="space-between" wrap="nowrap">
              <Text size="sm" lineClamp={1}>
                {index + 1}. {step.street}
              </Text>
              <Text size="sm" c="dimmed">
                {distanceToText(step.distance)}
              </Text>
            </Group>
          </Paper>
        </UnstyledButton>
      );
    })}
  </Stack>
);

export const RoutePanel = ({
  ref,
  searchByAddress,
  routes,
  loading,
  selectedRoute,
  selectedRouteIndex,
  onSelectRouteIndex,
  onBackToRouteList,
  selectedStepIndex,
  onSelectStepIndex,
  onTogglePickOrigin,
  onTogglePickDestination,
  hasOriginMarker,
  hasDestinationMarker,
  pickMode,
  onClearAll,
  transportMode,
  onTransportModeChange,
  mode,
  onModeChange,
  method,
  onMethodChange,
  scenic,
  onScenicChange,
  onScenicChangeEnd,
  snow,
  onSnowChange,
  onSnowChangeEnd,
  uphill,
  onUphillChange,
  onUphillChangeEnd,
  searchHistory,
  onSelectHistoryEntry,
  onClearHistory,
}: RoutePanelProps) => {
  const routeList = routes?.features ?? [];
  const routeCount = routeList.length;
  const hasRoute = routeCount > 0;
  const shouldConstrainPanel = mode === "advanced" || hasRoute;
  const detailOpen = selectedRouteIndex != null && selectedRoute != null;
  const clearDisabled = !hasOriginMarker && !hasDestinationMarker;
  const selectedRouteSteps = selectedRoute?.properties.steps ?? [];
  const [statsOpen, setStatsOpen] = useState(false);
  const statsVisible = statsOpen && routes != null;
  const [walkingSpeed, setWalkingSpeed] = useState(5);
  const [bikingSpeed, setBikingSpeed] = useState(15);
  const routeSpeedKmPerHour = getRouteSpeedKmPerHour(
    transportMode,
    walkingSpeed,
    bikingSpeed,
  );
  const getEstimatedTimeLabel = (distanceMeters: number) =>
    formatDuration(
      estimateRouteDurationMinutes(distanceMeters, routeSpeedKmPerHour),
    );
  const selectedRouteProgressionData =
    buildRouteProgressionData(selectedRouteSteps);

  const form = useForm({
    mode: "uncontrolled",
    initialValues: {
      origin: "",
      destination: "",
    },
  });

  useImperativeHandle(
    ref,
    () => ({
      setOrigin: (origin: string) => {
        form.setFieldValue("origin", origin);
      },
      setDestination: (destination: string) => {
        form.setFieldValue("destination", destination);
      },
      clearAllFields: () => {
        form.setFieldValue("origin", "");
        form.setFieldValue("destination", "");
      },
    }),
    [form],
  );

  const routeOverviewList = (
    <Stack gap="xs">
      {routeList.map((route) => {
        const routeIndex = route.properties.route_index;
        const recommendedRoute =
          routeCount > 1 && routeIndex === routes?.meta.recommended_route_index;

        return (
          <UnstyledButton
            key={routeIndex}
            onClick={() => {
              onSelectRouteIndex(routeIndex);
            }}
            w="100%"
          >
            <Paper withBorder p="sm" radius="md">
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <Box
                  w={12}
                  miw={12}
                  h={30}
                  mt={4}
                  bg={getRouteColor(routeIndex)}
                  style={{ borderRadius: 999 }}
                />
                <Stack gap={0}>
                  <Group justify="space-between">
                    <Group>
                      <Text fw={600}>
                        {getRouteTitle(route, routeCount, method)}
                      </Text>
                      {recommendedRoute && (
                        <IconStarFilled size="1rem" color="gold" />
                      )}
                    </Group>
                    <Badge variant="light" size="lg">
                      {distanceToText(route.properties.distance)}
                    </Badge>
                  </Group>
                  <Text size="sm" c="dimmed" mb="xs">
                    {getEstimatedTimeLabel(route.properties.distance)}
                  </Text>
                  <RouteObjectiveBadges route={route} />
                </Stack>
              </Group>
            </Paper>
          </UnstyledButton>
        );
      })}
    </Stack>
  );

  const routeDetailPane = selectedRoute ? (
    <Stack gap="md" mt="md" w="100%">
      <Group justify="flex-start" align="center">
        <ActionIcon
          variant="filled"
          onClick={onBackToRouteList}
          aria-label="Back to routes"
          style={{ flexShrink: 0 }}
        >
          <IconChevronLeft size="2rem" />
        </ActionIcon>
        <Title order={3}>
          {getRouteTitle(selectedRoute, routeCount, method)}
        </Title>
      </Group>

      {selectedRouteSteps.length > 0 ? (
        <Stack gap="xs">
          <Paper withBorder radius="md" p="sm">
            <Title order={4}>Info</Title>
            <Stack gap="sm">
              <Group justify="space-between">
                <Text fw={600}>Total Distance</Text>
                <Text fw={800}>
                  {distanceToText(selectedRoute.properties.distance)}
                </Text>
              </Group>
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <Stack gap={0}>
                  <Text fw={600}>Estimated Time</Text>
                  <Text size="sm" c="dimmed" w={200}>
                    Based on {String(routeSpeedKmPerHour)} km/h average{" "}
                    {transportMode === "walk" ? "walking" : "biking"} speed
                  </Text>
                </Stack>
                <Text fw={800}>
                  {getEstimatedTimeLabel(selectedRoute.properties.distance)}
                </Text>
              </Group>
              <Stack gap={0}>
                <Text fw={600}>Scores</Text>
                <Text size="sm" c="dimmed" mb="xs">
                  Higher is better
                </Text>
                <RouteObjectiveBadges route={selectedRoute} />
              </Stack>
            </Stack>
          </Paper>

          <Paper withBorder radius="md" p="sm">
            <Title order={4}>Progression</Title>
            <Text size="sm" c="dimmed" mb="sm">
              Scores throughout the route
            </Text>
            <LineChart
              style={{
                width: "100%",
                aspectRatio: 1.6,
              }}
              responsive
              data={selectedRouteProgressionData}
              margin={{
                top: 5,
                right: 8,
                left: 8,
                bottom: 5,
              }}
            >
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="stepLabel" />
              <YAxis
                width={40}
                domain={[0, 100]}
                tickFormatter={(value: number) => formatPercent(value)}
              />
              <RechartsTooltip formatter={formatTooltipPercent} />
              <Legend />
              <Line
                type="monotone"
                dataKey="uphillComfort"
                name={objectiveScoreLabels.uphillComfort}
                stroke="#2b8a3e"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 6 }}
              />
              <Line
                type="monotone"
                dataKey="scenicComfort"
                name={objectiveScoreLabels.scenicComfort}
                stroke="#f08c00"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 6 }}
              />
              <Line
                type="monotone"
                dataKey="snowlessComfort"
                name={objectiveScoreLabels.snowlessComfort}
                stroke="#1c7ed6"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 6 }}
              />
            </LineChart>
          </Paper>

          <Title order={3}>Steps</Title>
          <RouteStepList
            steps={selectedRouteSteps}
            selectedStepIndex={selectedStepIndex}
            onSelectStepIndex={onSelectStepIndex}
          />
        </Stack>
      ) : (
        <Text size="sm" c="dimmed">
          No route details yet.
        </Text>
      )}
    </Stack>
  ) : (
    <Box />
  );

  const routeListSection = hasRoute ? (
    <>
      <Divider my="md" />
      <Group justify="space-between" mb="md">
        <Group>
          <Text fw={600}>{routeCount === 1 ? "Route" : "Routes"}</Text>
          <Badge variant="light" size="lg">
            {routeCount}
          </Badge>
        </Group>
        <Button
          size="xs"
          variant={statsVisible ? "filled" : "light"}
          color="grape"
          onClick={() => {
            setStatsOpen((currentOpen) => !currentOpen);
          }}
          leftSection={<IconChartDots size="1rem" />}
        >
          Statistics
        </Button>
      </Group>
      {routeOverviewList}
    </>
  ) : null;

  const searchPane = (
    <Box w="100%" pr={detailOpen ? 8 : 0} miw={0}>
      <form
        onSubmit={form.onSubmit((values) => {
          void searchByAddress(values.origin, values.destination);
        })}
      >
        <Group align="end" wrap="nowrap">
          <TextInput
            label="Origin"
            placeholder="Origin"
            mt="md"
            flex={1}
            key={form.key("origin")}
            {...form.getInputProps("origin")}
          />
          <Tooltip label="Pick origin point on map" zIndex={2000} withArrow>
            <ActionIcon
              size="lg"
              variant={pickMode === "origin" ? "filled" : "light"}
              onClick={onTogglePickOrigin}
            >
              <Image alt="" src={markerIconUrl} w={12} h={20} />
            </ActionIcon>
          </Tooltip>
        </Group>

        <Group align="end" wrap="nowrap">
          <TextInput
            label="Destination"
            placeholder="Destination"
            mt="md"
            flex={1}
            key={form.key("destination")}
            {...form.getInputProps("destination")}
          />
          <Tooltip label="Pick end point on map" zIndex={2000} withArrow>
            <ActionIcon
              size="lg"
              variant={pickMode === "destination" ? "filled" : "light"}
              onClick={onTogglePickDestination}
            >
              <Image alt="" src={markerIconUrl} w={12} h={20} />
            </ActionIcon>
          </Tooltip>
        </Group>

        <Button
          variant="light"
          color="red"
          mt="md"
          leftSection={<IconTrash size="1rem" />}
          onClick={onClearAll}
          disabled={loading || clearDisabled}
        >
          Clear
        </Button>

        <Text mt="md" py="xs">
          Transport
        </Text>
        <SegmentedControl
          value={transportMode}
          onChange={(value) => {
            onTransportModeChange(value as TransportMode);
          }}
          fullWidth
          data={[
            { label: "Walking", value: "walk" },
            { label: "Bike", value: "bike" },
          ]}
        />

        <Group mt="md" py="xs">
          <Text>Mode</Text>
          <Tooltip
            label="Select whether you want to optimize the route for distance or multiple objectives"
            zIndex={2000}
            withArrow
          >
            <ActionIcon variant="light" size="sm">
              <IconQuestionMark size="1rem" />
            </ActionIcon>
          </Tooltip>
        </Group>

        <SegmentedControl
          value={mode}
          onChange={(value) => {
            onModeChange(value as Mode);
          }}
          fullWidth
          data={[
            { label: "Shortest", value: "shortest" },
            { label: "Advanced", value: "advanced" },
          ]}
        />

        {mode === "advanced" && (
          <>
            <SegmentedControl
              value={method}
              onChange={(value) => {
                onMethodChange(value as RouteSelectionMethod);
              }}
              fullWidth
              mt="md"
              data={[
                { label: "Weighted", value: "weighted" },
                { label: "Pareto", value: "pareto" },
              ]}
            />

            <Text mt="md">Scenic</Text>
            <Slider
              color="blue"
              size="xl"
              mt="sm"
              mb="lg"
              value={scenic}
              onChange={onScenicChange}
              onChangeEnd={onScenicChangeEnd}
              marks={[
                { value: 25, label: "25%" },
                { value: 50, label: "50%" },
                { value: 75, label: "75%" },
              ]}
            />

            <Text mt="md">Avoid Snow</Text>
            <Slider
              color="blue"
              size="xl"
              mt="sm"
              mb="lg"
              value={snow}
              onChange={onSnowChange}
              onChangeEnd={onSnowChangeEnd}
              marks={[
                { value: 25, label: "25%" },
                { value: 50, label: "50%" },
                { value: 75, label: "75%" },
              ]}
            />

            <Text mt="md">Avoid Uphill</Text>
            <Slider
              color="blue"
              size="xl"
              mt="sm"
              mb="lg"
              value={uphill}
              onChange={onUphillChange}
              onChangeEnd={onUphillChangeEnd}
              marks={[
                { value: 25, label: "25%" },
                { value: 50, label: "50%" },
                { value: 75, label: "75%" },
              ]}
            />
          </>
        )}

        <Button
          mt="md"
          disabled={loading || !form.values.origin || !form.values.destination}
          type="submit"
        >
          {loading ? "Searching..." : "Search"}
        </Button>
      </form>

      {routeListSection}
    </Box>
  );

  const searchTab = (
    <Tabs.Panel value="search">
      <Box style={{ overflow: "hidden" }} miw={0}>
        <Transition
          mounted={!detailOpen}
          transition="slide-right"
          duration={220}
          timingFunction="ease"
        >
          {(styles) => (
            <Box style={styles} w="100%" miw={0}>
              {searchPane}
            </Box>
          )}
        </Transition>
        <Transition
          mounted={detailOpen}
          transition="slide-left"
          duration={220}
          timingFunction="ease"
        >
          {(styles) => (
            <Box w="100%" style={styles} miw={0} pl={selectedRoute ? 8 : 0}>
              {routeDetailPane}
            </Box>
          )}
        </Transition>
      </Box>
    </Tabs.Panel>
  );

  const historyTab = (
    <Tabs.Panel value="history">
      <Group justify="space-between" mt="md" mb="sm">
        <Text fw={600}>Recent searches</Text>
        <Button
          size="compact-xs"
          variant="subtle"
          onClick={onClearHistory}
          disabled={searchHistory.length === 0}
        >
          Clear
        </Button>
      </Group>

      {searchHistory.length === 0 ? (
        <Text size="sm" c="dimmed">
          No recent searches yet.
        </Text>
      ) : (
        <Stack gap="xs">
          {searchHistory.map((entry) => (
            <UnstyledButton
              key={entry.key}
              onClick={() => {
                void onSelectHistoryEntry(entry);
              }}
            >
              <Paper withBorder p="sm" radius="md">
                <Text fw={600} lineClamp={1}>
                  {entry.originLabel}
                </Text>
                <Text size="sm" c="dimmed" lineClamp={1}>
                  {entry.destinationLabel}
                </Text>

                <Group gap="xs" mt="xs">
                  <Badge variant="light">
                    {entry.request.transportMode === "walk" ? "Walk" : "Bike"}
                  </Badge>
                  <Badge variant="light">
                    {entry.request.mode === "shortest"
                      ? "Shortest"
                      : entry.request.method === "weighted"
                        ? "Weighted"
                        : "Pareto"}
                  </Badge>
                </Group>

                <Text size="xs" c="dimmed" mt="xs">
                  {new Date(entry.createdAt).toLocaleString()}
                </Text>
              </Paper>
            </UnstyledButton>
          ))}
        </Stack>
      )}
    </Tabs.Panel>
  );

  const settingsTab = (
    <Tabs.Panel value="settings">
      <Text mt="md">Walking Speed (in km/h)</Text>
      <Slider
        color="blue"
        size="xl"
        mt="sm"
        mb="lg"
        value={walkingSpeed}
        onChange={setWalkingSpeed}
        domain={[1, 10]}
        min={1}
        max={10}
        marks={[
          { value: 1, label: "1" },
          { value: 5, label: "5" },
          { value: 10, label: "10" },
        ]}
      />
      <Text mt="xl">Biking Speed (in km/h)</Text>
      <Slider
        color="blue"
        size="xl"
        mt="sm"
        mb="lg"
        value={bikingSpeed}
        onChange={setBikingSpeed}
        domain={[1, 30]}
        min={1}
        max={30}
        marks={[
          { value: 1, label: "1" },
          { value: 15, label: "15" },
          { value: 30, label: "30" },
        ]}
      />
    </Tabs.Panel>
  );

  const tabs = (
    <Tabs defaultValue="search">
      <Tabs.List>
        <Tabs.Tab value="search">Search</Tabs.Tab>
        <Tabs.Tab value="history">History</Tabs.Tab>
        <Tabs.Tab value="settings">Settings</Tabs.Tab>
      </Tabs.List>
      {searchTab}
      {historyTab}
      {settingsTab}
    </Tabs>
  );

  return (
    <>
      <Paper
        shadow="xs"
        radius="md"
        style={{
          zIndex: 1000,
          borderTopRightRadius: statsVisible ? 0 : undefined,
          borderBottomRightRadius: statsVisible ? 0 : undefined,
        }}
        w={360}
        pos="absolute"
        top={12}
        left={12}
        opacity={0.95}
      >
        {shouldConstrainPanel ? (
          <ScrollArea.Autosize mah="calc(100dvh - 90px)" offsetScrollbars>
            <Box pt={20} pb={20} pl={20} pr={8}>
              {tabs}
            </Box>
          </ScrollArea.Autosize>
        ) : (
          <Box p={20}>{tabs}</Box>
        )}
      </Paper>
      <Transition mounted={statsVisible} transition="fade" duration={180}>
        {(styles) =>
          routes ? (
            <RouteStatsPanel
              routes={routes}
              selectedRouteIndex={selectedRouteIndex}
              onClose={() => {
                setStatsOpen(false);
              }}
              maxHeight="calc(100dvh - 90px)"
              style={styles}
            />
          ) : (
            <Box />
          )
        }
      </Transition>
    </>
  );
};
