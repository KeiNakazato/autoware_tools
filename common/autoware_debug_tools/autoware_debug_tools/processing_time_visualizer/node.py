import argparse
import curses
import json
import time
from typing import Dict
import uuid

import pyperclip
import rclpy
import rclpy.executors
from rclpy.node import Node
from tier4_debug_msgs.msg import ProcessingTimeTree as ProcessingTimeTreeMsg

from .print_tree import print_trees
from .topic_selector import select_topic
from .tree import ProcessingTimeTree
from .utils import exit_curses
from .utils import init_curses


class ProcessingTimeVisualizer(Node):
    def __init__(self, topic_waiting_sec=1.0, topic_name=None):
        super().__init__("processing_time_visualizer" + str(uuid.uuid4()).replace("-", "_"))
        self.topic_name = topic_name
        self.topic_waiting_sec = topic_waiting_sec
        self.subscriber = self.subscribe_processing_time_tree()
        self.quit_option = None
        self.trees: Dict[str, ProcessingTimeTree] = {}
        self.worst_case_tree: Dict[str, ProcessingTimeTree] = {}
        self.total_tree: Dict[str, ProcessingTimeTree] = {}
        self.stdcscr = init_curses()
        self.show_comment = False
        self.summarize_output = True
        print_trees("🌲 Processing Time Tree 🌲", self.topic_name, self.trees, self.stdcscr)

        self.create_timer(0.1, self.update_screen)

    def search_for_topic(self, topic_name: str) -> bool:
        for name, topic_types in self.get_topic_names_and_types():
            if name == topic_name:
                return True
        return False

    def wait_for_topics(self, condition_func, wait_sec: float) -> bool:
        s = time.time()
        while time.time() - s < wait_sec:
            if condition_func():
                return True
        return False

    def subscribe_processing_time_tree(self):
        # if topic name is specified with -t option
        if self.topic_name:
            topic_found = self.wait_for_topics(
                lambda: self.search_for_topic(self.topic_name), self.topic_waiting_sec
            )

            if not topic_found:
                self.get_logger().info(f"Specified topic '{self.topic_name}' not found.")
                self.get_logger().info("Exiting...")
                exit(1)
            else:
                subscriber = self.create_subscription(
                    ProcessingTimeTreeMsg,
                    self.topic_name,
                    self.callback,
                    10,
                )
        else:  # if topic name is not specified
            topics = []

            def condition_func():
                for name, topic_types in self.get_topic_names_and_types():
                    for topic_type in topic_types:
                        if (
                            topic_type == "tier4_debug_msgs/msg/ProcessingTimeTree"
                            and name not in topics
                        ):
                            topics.append(name)
                return len(topics) > 0

            topic_found = self.wait_for_topics(condition_func, self.topic_waiting_sec)

            if not topic_found:
                self.get_logger().info("No ProcessingTimeTree topic found")
                self.get_logger().info("Exiting...")
                exit(1)
            else:
                self.topic_name = curses.wrapper(select_topic, topics)
                subscriber = self.create_subscription(
                    ProcessingTimeTreeMsg,
                    self.topic_name,
                    self.callback,
                    10,
                )

        return subscriber

    def update_screen(self):
        key = self.stdcscr.getch()

        self.show_comment = not self.show_comment if key == ord("c") else self.show_comment
        self.summarize_output = (
            not self.summarize_output if key == ord("s") else self.summarize_output
        )
        logs = print_trees(
            "🌲 Processing Time Tree 🌲",
            self.topic_name,
            self.trees.values(),
            self.stdcscr,
            self.show_comment,
            self.summarize_output,
        )
        if key == ord("y"):
            pyperclip.copy(logs)
        if key == ord("q"):
            self.quit_option = "q"
            raise KeyboardInterrupt
        if key == ord("r"):
            self.quit_option = "r"
            raise KeyboardInterrupt

    def callback(self, msg: ProcessingTimeTreeMsg):
        tree = ProcessingTimeTree.from_msg(msg, self.summarize_output)
        self.trees[tree.name] = tree
        # worst case tree
        if tree.name not in self.worst_case_tree:
            self.worst_case_tree[tree.name] = tree
        else:
            self.worst_case_tree[tree.name] = (
                tree
                if tree.processing_time > self.worst_case_tree[tree.name].processing_time
                else self.worst_case_tree[tree.name]
            )
        # total tree
        if tree.name not in self.total_tree:
            self.total_tree[tree.name] = tree
        else:
            self.total_tree[tree.name].summarize_tree(tree)


def main(args=None):
    parser = argparse.ArgumentParser(description="Processing Time Visualizer")
    parser.add_argument("-t", "--topic", type=str, help="Specify the topic name to subscribe to")
    parser.add_argument(
        "-w", "--waiting-sec", type=float, default=1.0, help="Waiting time for topic"
    )
    parsed_args = parser.parse_args(args)

    rclpy.init(args=args)
    try:
        node = ProcessingTimeVisualizer(
            topic_name=parsed_args.topic, topic_waiting_sec=parsed_args.waiting_sec
        )
    except KeyboardInterrupt:
        exit_curses()
        return
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        node.destroy_node()
        exit_curses()
        if node.quit_option == "r":
            pyperclip.copy(json.dumps([v.__dict__() for v in node.worst_case_tree.values()]))
        if len(node.worst_case_tree) == 0:
            exit(1)

        print("🌲 Total Processing Time Tree 🌲")
        for tree in node.total_tree.values():
            tree_str = "".join(
                [line + "\n" for line in tree.to_lines(summarize=node.summarize_output)]
            )
            print(tree_str, end=None)

        print("⏰ Worst Case Execution Time ⏰")
        for tree in node.worst_case_tree.values():
            tree_str = "".join(
                [line + "\n" for line in tree.to_lines(summarize=node.summarize_output)]
            )
            print(tree_str, end=None)


if __name__ == "__main__":
    main()
