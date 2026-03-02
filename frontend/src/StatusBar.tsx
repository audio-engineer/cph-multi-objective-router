import { Affix, type MantineColor, Paper, Text } from "@mantine/core";

interface StatusBarProps {
  message: string;
  color: MantineColor;
}

export const StatusBar = ({ message, color }: StatusBarProps) => {
  return (
    <Affix position={{ bottom: 12, left: 12 }} zIndex={1200}>
      <Paper
        shadow="sm"
        radius="md"
        px="sm"
        py={6}
        withBorder
        w={360}
        opacity={0.95}
      >
        <Text size="sm" c={color}>
          {message}
        </Text>
      </Paper>
    </Affix>
  );
};
