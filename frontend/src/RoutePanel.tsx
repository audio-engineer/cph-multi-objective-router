import { type Ref, useImperativeHandle } from "react";
import {
  Button,
  Paper,
  Slider,
  TextInput,
  Text,
  Tabs,
  SegmentedControl,
  Divider,
  Group,
  Badge,
  Stack,
  ScrollArea,
  Tooltip,
  ActionIcon,
  UnstyledButton,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { IconQuestionMark, IconTrash } from "@tabler/icons-react";
import type { RouteStepResponse } from "@/client";
import markerIconUrl from "leaflet/dist/images/marker-icon.png?url";
import type { TravelMode } from "@/types/global.ts";
import type { Method, Mode } from "@/App.tsx";

export type PickMode = "start" | "end" | null;

export interface RoutePanelHandle {
  setFrom: (from: string) => void;
  clearFrom: () => void;
  setTo: (to: string) => void;
  clearTo: () => void;
  clearAllFields: () => void;
}

interface RoutePanelProps {
  ref?: Ref<RoutePanelHandle>;
  searchByAddress: (from: string, to: string) => Promise<void>;
  loading: boolean;
  distance: number | null;
  steps: RouteStepResponse[] | null;
  selectedStepIndex: number | null;
  onSelectStepIndex: (index: number | null) => void;
  onTogglePickStart: () => void;
  onTogglePickEnd: () => void;
  onClearAll: () => void;
  hasStartMarker: boolean;
  hasEndMarker: boolean;
  pickMode: PickMode;
  travelMode: TravelMode;
  setTravelMode: (mode: TravelMode) => void;
  mode: Mode;
  setMode: (mode: Mode) => void;
  method: Method;
  setMethod: (method: Method) => void;
  setScenic: (scenic: number) => void;
  setSnow: (snow: number) => void;
  setUphill: (uphill: number) => void;
}

const distanceToText = (distance: number) => {
  if (distance < 1000) {
    return `${distance.toFixed(0)} m`;
  }

  return `${(distance / 1000).toFixed(1)} km`;
};

export const RoutePanel = ({
  ref,
  searchByAddress,
  distance,
  loading,
  steps,
  selectedStepIndex,
  onSelectStepIndex,
  onTogglePickStart,
  onTogglePickEnd,
  hasStartMarker,
  hasEndMarker,
  pickMode,
  onClearAll,
  travelMode,
  setTravelMode,
  mode,
  setMode,
  method,
  setMethod,
  setScenic,
  setSnow,
  setUphill,
}: RoutePanelProps) => {
  const form = useForm({
    mode: "uncontrolled",
    initialValues: {
      from: "",
      to: "",
    },
  });

  useImperativeHandle(
    ref,
    () => ({
      setFrom: (from: string) => {
        form.setFieldValue("from", from);
      },
      clearFrom: () => {
        form.setFieldValue("from", "");
      },
      setTo: (to: string) => {
        form.setFieldValue("to", to);
      },
      clearTo: () => {
        form.setFieldValue("to", "");
      },
      clearAllFields: () => {
        form.setFieldValue("from", "");
        form.setFieldValue("to", "");
      },
    }),
    [form],
  );

  const clearDisabled = !hasStartMarker && !hasEndMarker;

  return (
    <Paper
      shadow="xs"
      radius="md"
      style={{
        zIndex: 1000,
      }}
      w={360}
      p="lg"
      pos="absolute"
      top={12}
      left={12}
      opacity={0.95}
    >
      <Tabs defaultValue="search">
        <Tabs.List>
          <Tabs.Tab value="search">Search</Tabs.Tab>
          <Tabs.Tab value="history">History</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="search">
          <form
            onSubmit={form.onSubmit((values) => {
              void searchByAddress(values.from, values.to);
            })}
          >
            <Group align="end" wrap="nowrap">
              <TextInput
                label="From"
                placeholder="From"
                mt="md"
                flex={1}
                key={form.key("from")}
                {...form.getInputProps("from")}
              />
              <Tooltip label="Pick start point on map" zIndex={2000} withArrow>
                <ActionIcon
                  size="lg"
                  variant={pickMode === "start" ? "filled" : "light"}
                  // disabled={hasStartMarker}
                  onClick={onTogglePickStart}
                >
                  <img
                    alt=""
                    src={markerIconUrl}
                    style={{ width: 12, height: 20 }}
                  />
                </ActionIcon>
              </Tooltip>
            </Group>
            <Group align="end" wrap="nowrap">
              <TextInput
                label="To"
                placeholder="To"
                mt="md"
                flex={1}
                key={form.key("to")}
                {...form.getInputProps("to")}
              />
              <Tooltip label="Pick end point on map" zIndex={2000} withArrow>
                <ActionIcon
                  size="lg"
                  variant={pickMode === "end" ? "filled" : "light"}
                  // disabled={hasEndMarker}
                  onClick={onTogglePickEnd}
                >
                  <img
                    alt=""
                    src={markerIconUrl}
                    style={{ width: 12, height: 20 }}
                  />
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
              value={travelMode}
              onChange={(tavelMode) => {
                setTravelMode(tavelMode as TravelMode);
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
              }}
              fullWidth
              data={[
                { label: "Fastest", value: "fastest" },
                { label: "Advanced", value: "advanced" },
              ]}
            />
            {mode === "advanced" && (
              <>
                <SegmentedControl
                  value={method}
                  onChange={(value) => {
                    setMethod(value as Method);
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
                  defaultValue={0}
                  onChange={setScenic}
                  marks={[
                    { value: 25, label: "25%" },
                    { value: 50, label: "50%" },
                    { value: 75, label: "75%" },
                  ]}
                />
                <Text mt="md">Avoid snow</Text>
                <Slider
                  color="blue"
                  size="xl"
                  mt="sm"
                  mb="lg"
                  defaultValue={0}
                  onChange={setSnow}
                  marks={[
                    { value: 25, label: "25%" },
                    { value: 50, label: "50%" },
                    { value: 75, label: "75%" },
                  ]}
                />
                <Text mt="md">Avoid uphill</Text>
                <Slider
                  color="blue"
                  size="xl"
                  mt="sm"
                  mb="lg"
                  defaultValue={0}
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
              disabled={loading || !form.values.from || !form.values.to}
              type="submit"
            >
              {loading ? "Searching..." : "Search"}
            </Button>
          </form>
          {(distance ?? (steps && steps.length > 0)) && (
            <>
              <Divider my="md" />
              <Group justify="space-between" align="center">
                <Text fw={600}>Route</Text>
                <Badge variant="light" size="lg">
                  {distance && distanceToText(distance)}
                </Badge>
              </Group>
              {steps && steps.length > 0 ? (
                <ScrollArea h={300} mt="md">
                  <Stack gap="xs">
                    {steps.map((step, index) => {
                      const selectedSt = index === selectedStepIndex;

                      return (
                        <UnstyledButton
                          key={`${step.street}-${String(index)}`}
                          onClick={() => {
                            if (selectedStepIndex === index) {
                              onSelectStepIndex(null);

                              return;
                            }

                            onSelectStepIndex(index);
                          }}
                          style={{ width: "100%" }}
                        >
                          <Paper
                            withBorder
                            p="xs"
                            radius="sm"
                            style={{
                              background: selectedSt
                                ? "rgba(0,0,0,0.06)"
                                : undefined,
                            }}
                          >
                            <Group
                              key={`${step.street}-${String(index)}`}
                              justify="space-between"
                              wrap="nowrap"
                            >
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
                </ScrollArea>
              ) : (
                <Text size="sm" c="dimmed" mt="sm">
                  No route details yet.
                </Text>
              )}
            </>
          )}
        </Tabs.Panel>
        <Tabs.Panel value="history">
          <Text mt="md">History...</Text>
        </Tabs.Panel>
      </Tabs>
    </Paper>
  );
};
