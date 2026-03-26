import { type Ref, useImperativeHandle } from "react";
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Divider,
  Flex,
  Group,
  Paper,
  ScrollArea,
  SegmentedControl,
  Slider,
  Stack,
  Tabs,
  Text,
  TextInput,
  Tooltip,
  Transition,
  UnstyledButton,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import {
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
import type { RouteSelectionMethod, Mode } from "@/App.tsx";
import { getRouteColor } from "@/utils.ts";

export type PickMode = "origin" | "destination" | null;

export interface RoutePanelHandle {
  setOrigin: (origin: string) => void;
  setDestination: (destination: string) => void;
  clearAllFields: () => void;
}

interface RoutePanelProps {
  ref?: Ref<RoutePanelHandle>;
  searchByAddress: (origin: string, destination: string) => Promise<void>;
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
  setTransportMode: (transportMode: TransportMode) => void;
  mode: Mode;
  setMode: (mode: Mode) => void;
  method: RouteSelectionMethod;
  setMethod: (method: RouteSelectionMethod) => void;
  scenic: number;
  setScenic: (scenic: number) => void;
  snow: number;
  setSnow: (snow: number) => void;
  uphill: number;
  setUphill: (uphill: number) => void;
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

    return `Alternative ${String(routeRank)}`;
  }

  if (routeCount === 1) {
    return "Route";
  }

  return `Route ${String(route.properties.route_index + 1)}`;
};

const getRouteSubtitle = (
  route: RouteFeature,
  method: RouteSelectionMethod,
) => {
  if (method === "pareto") {
    const routeRank =
      route.properties.pareto_rank ?? route.properties.route_index + 1;

    return `Pareto route ${String(routeRank)}`;
  }

  if (method === "weighted") {
    return "Weighted route";
  }

  return "Shortest route";
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
  setTransportMode,
  mode,
  setMode,
  method,
  setMethod,
  scenic,
  setScenic,
  snow,
  setSnow,
  uphill,
  setUphill,
}: RoutePanelProps) => {
  const routeList = routes?.features ?? [];
  const routeCount = routeList.length;
  const hasRoute = routeCount > 0;
  const shouldConstrainPanel = mode === "advanced" || hasRoute;
  const detailOpen = selectedRouteIndex != null && selectedRoute != null;
  const clearDisabled = !hasOriginMarker && !hasDestinationMarker;
  const selectedRouteSteps = selectedRoute?.properties.steps ?? [];

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
                <Group gap="sm" wrap="nowrap" align="flex-start">
                  <Box
                    w={12}
                    miw={12}
                    h={30}
                    mt={4}
                    bg={getRouteColor(routeIndex)}
                    style={{ borderRadius: 999 }}
                  />
                  <Box>
                    <Flex align="center">
                      <Text fw={600}>
                        {getRouteTitle(route, routeCount, method)}
                      </Text>
                      {recommendedRoute && (
                        <Box
                          ml="sm"
                          style={{ display: "flex", alignItems: "center" }}
                        >
                          <IconStarFilled size="1rem" color="gold" />
                        </Box>
                      )}
                    </Flex>
                    <Text size="sm" c="dimmed">
                      {getRouteSubtitle(route, method)}
                    </Text>
                  </Box>
                </Group>
                <Badge variant="light" size="lg">
                  {distanceToText(route.properties.distance)}
                </Badge>
              </Group>
            </Paper>
          </UnstyledButton>
        );
      })}
    </Stack>
  );

  const routeDetailPane = selectedRoute ? (
    <Stack gap="md" mt="md" w="100%">
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Group
          gap="xs"
          wrap="nowrap"
          align="center"
          style={{ flex: 1 }}
          miw={0}
        >
          <ActionIcon
            variant="subtle"
            onClick={onBackToRouteList}
            aria-label="Back to routes"
            style={{ flexShrink: 0 }}
          >
            <IconChevronLeft size="2rem" />
          </ActionIcon>
          <Box style={{ flex: 1 }} miw={0}>
            <Text fw={600} lineClamp={1}>
              {getRouteTitle(selectedRoute, routeCount, method)}
            </Text>
            <Text size="sm" c="dimmed" lineClamp={1}>
              {getRouteSubtitle(selectedRoute, method)}
            </Text>
          </Box>
        </Group>
        <Badge variant="light" size="lg" style={{ flexShrink: 0 }}>
          {distanceToText(selectedRoute.properties.distance)}
        </Badge>
      </Group>

      {selectedRouteSteps.length > 0 ? (
        <Box pr="xs">
          <RouteStepList
            steps={selectedRouteSteps}
            selectedStepIndex={selectedStepIndex}
            onSelectStepIndex={onSelectStepIndex}
          />
        </Box>
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
      <Group justify="space-between" align="center" mb="md">
        <Text fw={600}>{routeCount === 1 ? "Route" : "Routes"}</Text>
        <Badge variant="light" size="lg">
          {routeCount}
        </Badge>
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
              <img alt="" src={markerIconUrl} width={12} height={20} />
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
              <img alt="" src={markerIconUrl} width={12} height={20} />
            </ActionIcon>
          </Tooltip>
        </Group>
        <Button
          variant="light"
          color="red"
          mt="md"
          leftSection={<IconTrash size="1rem" />}
          onClick={onClearAll}
          disabled={clearDisabled}
        >
          Clear
        </Button>
        <Text mt="md" py="xs">
          Transport
        </Text>
        <SegmentedControl
          value={transportMode}
          onChange={(nextTransportMode) => {
            setTransportMode(nextTransportMode as TransportMode);
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
            setMode(value as Mode);

            if (value === "shortest") {
              setMethod(value as RouteSelectionMethod);
            }

            if (value === "advanced") {
              setMethod("weighted");
            }
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
                setMethod(value as RouteSelectionMethod);
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
              onChange={setScenic}
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
              onChange={setSnow}
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
              onChange={setUphill}
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

  const tabs = (
    <Tabs defaultValue="search">
      <Tabs.List>
        <Tabs.Tab value="search">Search</Tabs.Tab>
        <Tabs.Tab value="history">History</Tabs.Tab>
      </Tabs.List>
      {searchTab}
      <Tabs.Panel value="history">
        <Text mt="md">History...</Text>
      </Tabs.Panel>
    </Tabs>
  );

  return (
    <Paper
      shadow="xs"
      radius="md"
      style={{
        zIndex: 1000,
      }}
      w={360}
      // p="md"
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
  );
};
