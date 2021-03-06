from enum import Enum, auto
from random import randint

import custom_thread as c_thread
import game_entities as entities
import game_time as time
import message_dispatcher as dispatcher
from game_settings import g_vars


class State:

    def enter(self, entity):
        pass

    def execute(self, entity):
        pass

    def exit(self, entity):
        pass

    def on_message(self, entity, message):
        pass

class Stage(Enum):
        Done = auto()
        Traversing = auto()
        Gathering = auto()
        Delivering = auto()

class StateWaitForArtisan(State):
    def enter(self, entity):
        self.update_interval = 5
        self.time_since_last_update = 0

    def execute(self, entity):
        if self.time_since_last_update >= self.update_interval:
            free_artisans = []
            target_artisans = []
            target_artisan_count = 0
            # count number of target_artisans and free artisans
            for artisan in entity.owner.entities_where(lambda e: isinstance(e, entities.UnitArtisan) and e.is_visible):
                if artisan.profession == entity.artisan_required:
                    target_artisan_count += 1
                    target_artisans.append(artisan)
                elif artisan.profession == entities.UnitArtisan.Profession.Free:
                    free_artisans.append(artisan)
            # check to see if any more target_artisans needs to be created (currently 1)
            if target_artisan_count < 1:
                # assign artisan if needed
                if free_artisans:
                    free_artisans[0].profession = entity.artisan_required
                    free_artisans[0].fsm.change_state(StateArtisan())
                # has no free artisans -> order one
                else:
                    entity.owner.prepend_goal(["Unit", "Artisan", 4]) # currently maximun needed artisans
                    # can be incremented each time a structure requiring an artisan is built

            # try and get an artisan to come
            for artisan in target_artisans:
                if artisan.fsm.is_in_state(StateArtisan):
                    message = dispatcher.Message(entity, dispatcher.MSG.ArtisanNeeded)
                    artisan.fsm.handle_message(message)
                    break

            # reset timer   
            self.time_since_last_update = 0
        self.time_since_last_update += time.delta_time

    def exit(self, entity):
        pass

    def on_message(self, entity, message):
        # artisan has arrived
        if message.msg == dispatcher.MSG.ArtisanArrived:
            # save reference to artisan
            entity.artisan_unit = message.sender
            # lock artisan
            message.sender.fsm.change_state(StateLocked())
            # if-check depends on if the structure has been built or not
            if message.sender.profession == entities.UnitArtisan.Profession.Builder:
                # needs to be built
                entity.fsm.change_state(StateProduced())
            else:
                # has been built and received managing artisan
                entity.fsm.change_state(StateIdle())
            return True

        return False

class StateArtisan(State):
    def enter(self, entity):
        self.stage = Stage.Done
        self.finding_path = False
        self.target_structure = None

    def execute(self, entity):
        pass       

    def exit(self, entity):
        pass

    def on_message(self, entity, message):
        # Go where work is needed if not currently walking
        if message.msg == dispatcher.MSG.ArtisanNeeded and not self.finding_path:
            self.finding_path = True
            self.target_structure = message.sender
            find_path(entity, entity.location, message.sender.location, get_path_callback)
            return True
        # has arrived to work -> notify structure
        if message.msg == dispatcher.MSG.ArrivedAtGoal:
            message = dispatcher.Message(entity, dispatcher.MSG.ArtisanArrived)
            self.target_structure.fsm.handle_message(message)
            return True

        return False

class StateProduced(State):
    def enter(self, entity):
        self.accumulated_production = 0

    def execute(self, entity):
        self.accumulated_production += time.delta_time
        if self.accumulated_production >= entity.production_time:
            entity.production_spawn()

    def exit(self, entity):
        pass

    def on_message(self, entity, message):
        pass

class StateLocked(State):
    pass

class StateIdle(State):
    def enter(self, entity):
        entity.is_idle = True

    def execute(self, entity):
        pass

    def exit(self, entity):
        entity.is_idle = False

    def on_message(self, entity, message):
        pass

class StateGather(State):

    def enter(self, entity):
        self.stage = Stage.Done
        self.finding_path = False
        self.gather_progress = 0
        self.gather_completion = False
        self.target_resource = None

    def execute(self, entity):
        if self.stage is Stage.Done:
            if not self.finding_path and entity.owner.target_resource:
                self.target_resource = entity.owner.target_resource # save which recourse worker set out to gather
                goal = entity.owner.get_resource_location(entity.location, self.target_resource[2]) # class
                if goal:
                    self.finding_path = True
                    find_path(entity, entity.location, goal, get_path_callback)

        elif self.stage is Stage.Traversing:
            pass

        elif self.stage is Stage.Gathering:
            # gathering is done but doesn't have a path
            if self.gather_completion and not self.finding_path:
                self.finding_path = True
                goal = entity.owner.start_position
                find_path(entity, entity.location, goal, self.__get_delivery_path_callback)
            # if gathering is completed
            elif self.gather_progress >= g_vars[self.target_resource[0]][self.target_resource[1]]["GatherTime"]:
                self.gather_completion = True
            # tick progress
            self.gather_progress += time.delta_time

        elif self.stage is Stage.Delivering:
            pass

    def exit(self, entity):
        pass

    def on_message(self, entity, message):
        if message.msg == dispatcher.MSG.ArrivedAtGoal:
            if self.stage is Stage.Traversing:
                # check if tile has wanted resource remaining
                tile = entity.gamemap.get_background_tile(entity.location)
                if tile.has_free_resource_type(self.target_resource[2]):
                    # occupy that resource and shange stage
                    tile.occupy_resource(self.target_resource[2])
                    self.stage = Stage.Gathering
                # else entity will find try to find another resource
                else:
                    self.stage = Stage.Done

            elif self.stage is Stage.Delivering:
                if entity.carried_resource:
                    # increment at base
                    entity.owner.add_resource([entity.carried_resource])
                    # remove resource from self
                    entity.carried_resource = None
                self.stage = Stage.Done

            return True

        return False

    def __get_delivery_path_callback(self, entity, result):
        self.finding_path = False
        if result:
            # safe to reset progress when path has been found
            self.gather_progress = 0
            self.gather_completion = False
            # deduct one resource from tile and carry it
            tile = entity.gamemap.get_background_tile(entity.location)
            entity.carried_resource = tile.deduct_resource(self.target_resource[2])
            # change stage and transport resource
            self.stage = Stage.Delivering
            entity.set_path(result)

class StateExplore(State):

    def enter(self, entity):
        self.stage = Stage.Done
        self.finding_path = False

    def execute(self, entity):
        if self.stage is Stage.Done and not self.finding_path:
            self.finding_path = True
            loc = entity.location
            goal = (randint(0, entity.gamemap.tile_width - 1), (randint(0, entity.gamemap.tile_height - 1)))
            find_path(entity, loc, goal, get_path_callback, False)

    def exit(self, entity):
        pass

    def on_message(self, entity, message):
        if message.msg == dispatcher.MSG.ArrivedAtGoal:
            self.stage = Stage.Done
            return True

        return False

# Method will create a separate thread and calculate a path between two points
def find_path(entity, location, goal, __callback, fog=True):
        fog_filter_funtion = None
        # if Astar should find path through fog, pass it a function to do so
        if fog:
            fog_filter_funtion = entity.owner.gamemap.location_is_discovered
        thread = c_thread.BaseThread(
            target=entity.gamemap.get_path,
            target_args=(location, goal, fog_filter_funtion),
            callback=__callback,
            callback_args=[entity]
        )
        thread.start()

def get_path_callback(entity, result):
    entity.fsm.currentState.finding_path = False
    if result:
        entity.fsm.currentState.stage = Stage.Traversing
        entity.set_path(result)
